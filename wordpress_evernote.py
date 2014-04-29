#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import time
import mimetypes
import binascii
import hashlib
import urllib
import urllib2
from string import Template

# WordPress API:
from wordpress_xmlrpc import Client #, WordPressPost
#from wordpress_xmlrpc.methods.posts import GetPosts, NewPost
#from wordpress_xmlrpc.methods.users import GetUserInfo
#from wordpress_xmlrpc.compat import xmlrpc_client
from wordpress_xmlrpc.methods import media#, posts

#Evernote API:
from evernote.api.client import EvernoteClient
import evernote.edam.type.ttypes as Types
import evernote.edam.error.ttypes as Errors
from evernote.edam.notestore import NoteStore

import settings
#from settings import *

## Initialize module logging
formatter = logging.Formatter(u'%(message)s')
logger = logging.getLogger(u'wordpress-evernote')
logger.setLevel(logging.DEBUG)
if hasattr(logger, 'handlers') and not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter(u'%(message)s'))
    logger.addHandler(ch)
    fh = logging.FileHandler(u'tomato-cmd.log', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
                    u'%(asctime)s\t%(levelname)s\t%(message)s'))
    logger.addHandler(fh)

wp = Client(settings.wpXmlRpcUrl, settings.wpUsername, settings.wpPassword)

class UrlParser:
    
    def __init__(self, url):
        self.url = url
        self.schema, url = urllib2.splittype(url)
        host, path = urllib2.splithost(url)
        userpass, host = urllib2.splituser(host)
        if userpass:
            self.user, self.password = urllib2.splitpasswd(userpass)
        path, self.querystring = urllib.splitquery(path)
        self.query = self.querystring and self.querystring.split('&') or []
        #urllib.splitquery(url)
        self.host, self.port = urllib2.splitport(host)
        path, self.tag = urllib2.splittag(path)
        self.path = path.strip('/')
    
    def path_parts(self):
        return self.path.split('/')

class WordPressImageAttachment:
    
    _slots = frozenset(('id', 'title', 'link', 'parent', 'caption',
                        'date_created', 'description'))
    
    def __init__(self, wp_media_item):
        for slot in self._slots:
            if not hasattr(wp_media_item, slot):
                logger.error('WordPress MediaItem "%s" has not attribute "%s"',
                             wp_media_item, slot)
                raise RuntimeError()
            self.__dict__[slot] = getattr(wp_media_item, slot)
        self.filename = UrlParser(self.link).path_parts()[-1]
            
    def __unicode__(self):
        return u'<%s: %s (%s)>' % (self.__class__.__name__,
                                   self.title, self.id)
    
    def __str__(self):
        return unicode(self).encode('utf-8')
    
    def image(self):
        "Returns a file-like object for reading image data."
        return urllib2.urlopen(self.link)

def wp_attachment_generator(parent_id=''):
    """Generates WordPress attachment objects.
    """
    for media_item in wp.call(media.GetMediaLibrary({'parent_id':
                                                     str(parent_id)})):
        wpImage = WordPressImageAttachment(media_item)
        logging.debug(u'Yielding WordPress media item %s', wpImage)
        yield wpImage

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
        body = src_file.read()
        data = Types.Data(body=body, size=len(body),
                          bodyHash=hashlib.md5(body).digest())
        attr = Types.ResourceAttributes(fileName=filename.encode('utf-8'))
        resource = Types.Resource(data=data, mime=mime, attributes=attr)
        resource_tag = '<en-media type="%s" hash="%s" />' % \
                       (mime, binascii.hexlify(data.bodyHash))
        return resource, resource_tag.encode('utf-8')
        
    def __init__(self, token, sandbox=False):
        self.cached_notebook = None
        self._init_en_client(token, sandbox)
        self._notes_metadata_page_size = 100
        self._notebook_list = None
    
    def _get_notebook(self, notebook_name):
        if not self._notebook_list:
            self._notebook_list = self._note_store.listNotebooks()
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
    
    def _notes_metadata_generator(self, note_filter, spec,
                                  start_offset=0, page_size=None):
        # API call wrapped in generator to simplify pagination and mocking.
        offset = start_offset
        if not page_size:
            page_size = self.notes_metadata_page_size()
        while True:
            try:
                notes_metadata = self._note_store.findNotesMetadata(
                                                            self._client.token,
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
            except Errors.EDAMSystemException, e:
                # TODO: more flexible error handling? callbacks?
                if e.errorCode == Errors.EDAMErrorCode.RATE_LIMIT_REACHED:
                    wait_time = e.rateLimitDuration + 5
                    logger.warn(u'Evernote rate limit reached :-( '
                                u'Waiting %d seconds before retrying' %
                                (wait_time))
                    time.sleep(wait_time)
                    logger.debug(u'Finished waiting for rate limit reset.')
    
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
    
    def saveNoteToNotebook(self, note, in_notebook=None):
        # If no notebook specified - default notebook is used
        notebook = in_notebook and self._get_notebook(in_notebook)
        if notebook:
            note.notebookGuid = notebook.guid
        logger.info('Saving note "%s" to Evernote' % (note.title))
        self._note_store.createNote(self._client.token, note)
    
    def updateNote(self, note):
        self._note_store.updateNote(self._client.token, note)
                
def save_wp_image_to_evernote(en_wrapper, notebook_name, wp_image,
                              force=False):
    # lookup existing WordPress image note
    note_title = u'%s <%s>' % (wp_image.filename, wp_image.id)
    image_note = en_wrapper.getSingleNoteByTitle(note_title, notebook_name)
    if not image_note or force:
        # prepare resource and note
        resource, resource_tag = en_wrapper.makeResource(wp_image.image(),
                                                         wp_image.filename)
        note_content = '%s\r\n<hr/>\r\n' % (resource_tag)
        for attr in WordPressImageAttachment._slots:
            note_content += '<div>%s=%s</div>\r\n' % (attr,
                                                      getattr(wp_image, attr))
        wp_image_note = en_wrapper.makeNote(title=note_title,
                                            content=note_content,
                                            resources=[resource])
    if image_note:
        # note exists
        logger.info('WP Image note "%s" exists in Evernote', note_title)
        if force:
            logger.info('Updating note with WordPress version.')
            # update existing note with overwritten content
            wp_image_note.guid = image_note.guid
            en_wrapper.updateNote(wp_image_note)
        else:
            logger.debug('Skipping note update')
    else:
        # create new note
        logger.info('Creating new WP Image note "%s"', note_title)
        en_wrapper.saveNoteToNotebook(wp_image_note, notebook_name)

def main():
    en_wrapper = EvernoteApiWrapper(settings.enDevToken_PRODUCTION)
    for wp_image in wp_attachment_generator(457):
        save_wp_image_to_evernote(en_wrapper, '.zImages', wp_image)

if '__main__' == __name__:
    main()
