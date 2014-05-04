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
    
    @classmethod
    def noteTemplate(cls):
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
    
    @classmethod
    def makeResource(cls, src_file, filename, mime=None):
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
    
    @classmethod
    def parseNoteLinkUrl(cls, url):
        """Returns parsed link object.
        Ref: http://dev.evernote.com/doc/articles/note_links.php
        Currently supporting only notes in synced notebooks, and not linked.
        (e.g. no `client specific id` and `linked notebook guid`)
        """
        link = namedtuple('EvernoteLink', ['user_id', 'shard_id', 'noteGuid',])
        note_link_match = re.match('evernote\:\/\/\/view\/'
                                   '(?P<uid>\d+)/(?P<sid>s\d+)\/'
                                   '(?P<note_id>[0-9a-f]{8}-[0-9a-f]{4}-'
                                   '[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'
                                   '\/(?P=note_id)\/', url)
        if note_link_match:
            d = note_link_match.groupdict()
            link.user_id = d['uid']
            link.shard_id = d['sid']
            link.noteGuid = d['note_id']
            return link
        else:
            logger.error('Failed parsing Evernote note link %s', url)
            raise RuntimeError()
        
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
            page_size = self.notes_metadata_page_size()
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
    
    def getNotesByTitle(self, title, in_notebook=None, page_size=None):
        notebook = in_notebook and self._get_notebook(in_notebook)
        # remove occurrences of '"' because Evernote ignores it in search
        query = 'intitle:"%s"' % (title.replace('"', '').encode('utf-8'))
        note_filter = NoteStore.NoteFilter(words=query,
                                       notebookGuid=notebook and notebook.guid)
        spec = NoteStore.NotesMetadataResultSpec(includeTitle=True,
                                                 includeUpdated=True)
        return self._notes_metadata_generator(note_filter, spec,
                                              page_size=page_size)
    
    def getSingleNoteByTitle(self, title, in_notebook=None):
        ret_note = None
        for offset, note_metadata in self.getNotesByTitle(title,
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
        self._note_store.updateNote(self._client.token, note)
    
    @ratelimit_wait_and_retry
    def getNote(self, note_guid, with_content_flag=True):
        return self._note_store.getNote(self._client.token,
                                        note_guid, with_content_flag,
                                        False, False, False)