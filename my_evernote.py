#!/usr/bin/python
# -*- coding: utf-8 -*-

import time
import re
import mimetypes
import binascii
import hashlib
from string import Template
from collections import namedtuple

#Evernote API:
from evernote.api.client import EvernoteClient
import evernote.edam.type.ttypes as Types
import evernote.edam.error.ttypes as Errors
from evernote.edam.notestore import NoteStore

import common

logger = common.logger.getChild('my-evernote')

note_link_re = re.compile('evernote\:\/\/\/view\/(?P<uid>\d+)/(?P<sid>s\d+)\/'
                          '(?P<note_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                          '[0-9a-f]{4}-[0-9a-f]{12})\/(?P=note_id)\/')

# https://www.evernote.com/shard/s123/nl/112233/abcd1234-1234-abcd-1234-abcd1234abcd
note_url_re = re.compile('https\:\/\/www\.evernote\.com\/shard\/'
                          '(?P<sid>s\d+)\/nl\/(?P<uid>\d+)\/'
                          '(?P<note_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
                          '[0-9a-f]{4}-[0-9a-f]{12})\/?')

def ratelimit_wait_and_retry(func):
    def runner(*args, **kwargs):
        while True:
            try:
                return func(*args, **kwargs)
            except Errors.EDAMSystemException, e:
                # TODO: more flexible error handling? callbacks?
                if e.errorCode == Errors.EDAMErrorCode.RATE_LIMIT_REACHED:
                    wait_time = e.rateLimitDuration + 5
                    logger.warn(u'Evernote rate limit reached :-( '
                                u'Waiting %d seconds before retrying' %
                                (wait_time))
                    time.sleep(wait_time)
                    logger.debug(u'Finished waiting for rate limit reset.')
    return runner

class EvernoteApiWrapper():
    
    _cache = dict()
    
    @staticmethod
    def noteTemplate():
        return Template('\r\n'.join([
          '<?xml version="1.0" encoding="UTF-8"?>',
          '<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">',
          '',
          '<en-note style="word-wrap: break-word; -webkit-nbsp-mode: space; '
          '-webkit-line-break: after-white-space;">',
          '${content}',
          '</en-note>',
          ]))
    
    @classmethod
    def makeNote(cls, title, content, in_notebook_guid=None, resources=None,
                 tags=[], created=None, updated=None):
        note = Types.Note(title=title, tagNames=tags)
        note.content = cls.noteTemplate().safe_substitute({'content': content})
        note.resources = resources
        if in_notebook_guid:
            note.notebookGuid = in_notebook_guid
        note.created = created
        note.updated = updated
        return note
    
    @staticmethod
    def makeResource(src_file, filename, mime=None):
        if not mime:
            mime = mimetypes.guess_type(filename)[0]
        if not mime:
            mime = u'application/octet-stream'
            logger.warning(u'Failed guessing mimetype for "%s" '
                            '(defaulting to "%s")' % (filename, mime))
        # mimetype workarounds:
        if 'image/x-png' == mime:
            # seems like Evernote (Windows) will display
            #  the image inline in the note only this way.
            mime = 'image/png'
        if 'image/pjpeg' == mime:
            # seems like Evernote (Windows) will display
            #  the image inline in the note only this way.
            mime = 'image/jpeg'
        body = src_file.read()
        data = Types.Data(body=body, size=len(body),
                          bodyHash=hashlib.md5(body).digest())
        attr = Types.ResourceAttributes(fileName=filename.encode('utf-8'))
        resource = Types.Resource(data=data, mime=mime, attributes=attr)
        resource_tag = '<en-media type="%s" hash="%s" />' % \
                       (mime, binascii.hexlify(data.bodyHash))
        return resource, resource_tag.encode('utf-8')
    
    @staticmethod
    def is_evernote_url(url):
        return url and ((url.startswith('evernote:///view/') or
                         url.startswith('https://www.evernote.com/')))
    
    @staticmethod
    def parseNoteLinkUrl(url):
        """Returns parsed link object.
        Ref: http://dev.evernote.com/doc/articles/note_links.php
        Currently supporting only notes in synced notebooks, and not linked.
        (e.g. no `client specific id` and `linked notebook guid`)
        """
        link = namedtuple('EvernoteLink', ['user_id', 'shard_id', 'noteGuid',])
        def match_to_link(m):
            d = m.groupdict()
            link.user_id = d['uid']
            link.shard_id = d['sid']
            link.noteGuid = d['note_id']
            return link
        note_link_match = note_link_re.match(url)
        if note_link_match:
            return match_to_link(note_link_match)
        note_url_match = note_url_re.match(url)
        if note_url_match:
            return match_to_link(note_url_match)
        logger.error('Failed parsing Evernote note link %s', url)
        raise RuntimeError()
    
    @classmethod
    def get_note_guid(cls, en_link_or_url_or_guid):
        """Return an Evernote note GUID from link string.
        
        The link can be of several forms:
        - Just a GUID (that's trivial).
        - Evernote link of the form evernote:///view/...
        - Evernote URL of the form https://www.evernote.com/...
        """
        guid = en_link_or_url_or_guid
        if cls.is_evernote_url(guid):
            guid = cls.parseNoteLinkUrl(guid).noteGuid
        return guid
    
    def __init__(self, token, sandbox=False):
        self.cached_notebook = None
        self._init_en_client(token, sandbox)
        self._notes_metadata_page_size = 100
        self._notebook_list = None
    
    @ratelimit_wait_and_retry
    def _listNotebooks(self):
        return self._note_store.listNotebooks()
    
    def _get_notebook(self, notebook_name):
        if not self._notebook_list:
            self._notebook_list = self._listNotebooks()
        for nb in self._notebook_list:
            if nb.name == notebook_name:
                return nb
        logger.warning(u'Could not find notebook "%s"', notebook_name)
    
    @property
    def notes_metadata_page_size(self):
        return self._notes_metadata_page_size
    @notes_metadata_page_size.setter
    def notes_metadata_page_size(self, value):
        self._notes_metadata_page_size = value
    
    def _init_en_client(self, token, sandbox):
        # Client initialization code in dedicated function
        #  to simplify mocking for unit tests.
        self._client = EvernoteClient(token=token, sandbox=sandbox)
        self._note_store = self._client.get_note_store()
    
    @ratelimit_wait_and_retry
    def _findNotesMetadata(self, *args, **kwargs):
        return self._note_store.findNotesMetadata(*args, **kwargs)
    
    def _notes_metadata_generator(self, note_filter, spec,
                                  start_offset=0, page_size=None):
        # API call wrapped in generator to simplify pagination and mocking.
        offset = start_offset
        if not page_size:
            page_size = self.notes_metadata_page_size
        while True:
            notes_metadata = self._findNotesMetadata(self._client.token,
                                                     note_filter,
                                                     offset, page_size,
                                                     spec)
            for note_offset, note in enumerate(notes_metadata.notes,
                                               offset):
                # yield also note offset in query,
                #  to allow efficient re-entry in case of rate limit.
                yield note_offset, note
            if notes_metadata.startIndex + page_size >= \
                    notes_metadata.totalNotes:
                break
            offset += page_size
    
    def get_notes_by_query(self, query, in_notebook=None, page_size=None):
        """Generate Evernote notes matched by query in a notebook."""
        notebook = in_notebook and self._get_notebook(in_notebook)
        query = query.encode('utf-8')
        note_filter = NoteStore.NoteFilter(
            words=query,
            notebookGuid=notebook and notebook.guid)
        spec = NoteStore.NotesMetadataResultSpec(includeTitle=True,
                                                 includeUpdated=True)
        return self._notes_metadata_generator(note_filter, spec,
                                              page_size=page_size)
    
    def get_notes_by_title(self, title, in_notebook=None, page_size=None):
        """Generate Evernote notes matching a title in a notebook."""
        #notebook = in_notebook and self._get_notebook(in_notebook)
        # remove occurrences of '"' because Evernote ignores it in search
        query = 'intitle:"%s"' % (title.replace('"', '').encode('utf-8'))
        return self.get_notes_by_query(query, in_notebook, page_size)
    
    def getSingleNoteByTitle(self, title, in_notebook=None):
        ret_note = None
        for offset, note_metadata in self.get_notes_by_title(title,
                                                             in_notebook, 2):
            if 0 == offset:
                ret_note = note_metadata
            else:
                logger.warn('More than 1 note matches query')
                break
        return ret_note
    
    @ratelimit_wait_and_retry
    def _createNote(self, note):
        self._note_store.createNote(self._client.token, note)
    
    def saveNoteToNotebook(self, note, in_notebook=None):
        # If no notebook specified - default notebook is used
        notebook = in_notebook and self._get_notebook(in_notebook)
        if notebook:
            note.notebookGuid = notebook.guid
        logger.info('Saving note "%s" to Evernote' % (note.title))
        self._createNote(note)
    
    @ratelimit_wait_and_retry
    def updateNote(self, note):
        """Update a note in the Evernote note store.
        
        :param note: The note to update.
        :type note: Types.Note
        """
        self._note_store.updateNote(self._client.token, note)
    
    @ratelimit_wait_and_retry
    def get_resource_data(self, guid):
        """Get Evernote resource data by GUID.
        
        :param guid: The requested resource GUID.
        """
        if guid in self._cache:
            return self._cache[guid]
        self._cache[guid] = self._note_store.getResourceData(
            self._client.token, guid)
        return self._cache[guid]
    
    @ratelimit_wait_and_retry
    def get_note(self, genlink, with_content=True, with_resource_data=False):
        """Get Evernote Note object by GUID or generalized link.
        
        :param genlink: The requested note generalized link or GUID.
        :param with_content: If `True`, includes note content in response.
        :param with_resource_data: If `True`, includes resources data in
                                   response.
        """
        note_guid = self.get_note_guid(genlink)
        if note_guid in self._cache:
            return self._cache[note_guid]
        note = self._note_store.getNote(self._client.token,
                                        note_guid,
                                        with_content,
                                        with_resource_data,
                                        False, False)
        # Decode strings so rest of program can assume Unicode.
        note.title = note.title.decode('utf-8')
        note.content = note.content.decode('utf-8')
        self._cache[note_guid] = note
        return note
