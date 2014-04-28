#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import time
import mimetypes
import binascii
import hashlib
import urllib
import urllib2

# WordPress API:
from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods.posts import GetPosts, NewPost
from wordpress_xmlrpc.methods.users import GetUserInfo
from wordpress_xmlrpc.compat import xmlrpc_client
from wordpress_xmlrpc.methods import media, posts

#Evernote API:
from evernote.api.client import EvernoteClient
import evernote.edam.type.ttypes as Types
import evernote.edam.error.ttypes as Errors
from evernote.edam.notestore import NoteStore

from settings import *

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

wp = Client(wpXmlRpcUrl, wpUsername, wpPassword)

enDevToken = enDevToken_PRODUCTION
enClient = EvernoteClient(token=enDevToken, sandbox=(enDevToken==enDevToken_SANDBOX))
enNoteStore = enClient.get_note_store()

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

def wp_attachment_generator(parent_id=''):
    """Generates WordPress attachment objects.
    """
    for media_item in wp.call(media.GetMediaLibrary({'parent_id':
                                                     str(parent_id)})):
        wpImage = WordPressImageAttachment(media_item)
        logging.debug(u'Yielding WordPress media item %s', wpImage)
        yield wpImage

def file_to_resource(res_file, filename, mime=None):
    if not mime:
        mime = mimetypes.guess_type(filename)[0]
    if not mime:
        mime = u'application/octet-stream'
        logger.warning(u'Failed guessing mimetype for "%s" '
                        '(defaulting to "%s")' % (filename, mime))
    if g_DRYRUN:
        body = u'Hello, World!'
    else:
        body = res_file.read()
    data = Types.Data(body=body, size=len(body),
                      bodyHash=hashlib.md5(body).digest())
    attr = Types.ResourceAttributes(fileName=filename.encode('utf-8'))
    res = Types.Resource(data=data, mime=mime, attributes=attr)
    return res

def note_with_resources(noteTitle, resources, parentNotebook=None,
                        tags=[], created=None, updated=None):
    myNote = Types.Note(title=noteTitle, tagNames=tags)
    nBody = '<?xml version="1.0" encoding="UTF-8"?>'
    nBody += '<!DOCTYPE en-note SYSTEM '    \
             '"http://xml.evernote.com/pub/enml2.dtd">'
    nBody += '<en-note>'
    nBody += '<br />' * 2
    myNote.resources = resources
    for res in resources:
        nBody += '<en-media type="%s" hash="%s" /><br />' %     \
                 (res.mime, binascii.hexlify(res.data.bodyHash))
    nBody += '</en-note>'
    myNote.content = nBody
    # parentNotebook is optional; if omitted, default notebook is used
    if parentNotebook and hasattr(parentNotebook, 'guid'):
        myNote.notebookGuid = parentNotebook.guid
    myNote.created = created
    myNote.updated = updated
    return myNote

class EvernoteAdaptor():
    notebook_list = None
    
    @classmethod
    def _get_notebook(cls, notebook_name):
        if not cls.notebook_list:
            cls.notebook_list = enNoteStore.listNotebooks()
        for nb in cls.notebook_list:
            if nb.name == notebook_name:
                return nb
        logger.warning(u'Could not find notebook "%s" - '
                        'using default notebook' %
                        (notebook_name))
        
    def __init__(self, title_pattern, notebook=None, tags=[]):
        self.title_pattern = title_pattern
        self.notebook = notebook
        self.cached_notebook = None
        self.tags = [tag.encode('utf-8') for tag in tags]
        self.tags.append(u'~MyFTTT'.encode('utf-8'))

    def save_resource_to_evernote(self, event):
        while True:
            try:
                if self.notebook and not self.cached_notebook:
                    self.cached_notebook = self._get_notebook(self.notebook)
                self.event = event
                note_title = ''
                logger.debug(u'Checking for existing note "%s"' % (note_title))
                query = 'filename:"%s"' % (event[u'filename'].encode('utf-8'))
        ##        query = 'intitle:"%s"'  % (note_title.encode('utf-8'))
        ##        if self.cached_notebook:
        ##            query = 'notebook:"%s" %s' % (self.cached_notebook.name, query)
                note_filter = NoteStore.NoteFilter(words=query)
                spec = NoteStore.NotesMetadataResultSpec(includeTitle=True)
                note_list = enNoteStore.findNotesMetadata(enDevToken, note_filter,
                                                          0, 10, spec)
                for note in note_list.notes:
                    if note.title == note_title.encode('utf-8'):
                        logger.debug(u'Note "%s" exists. Skipping.' % (note_title))
                        return False
                logger.info(u'Creating note "%s"' % (note_title))
                resource = file_to_resource(event[u'fileobj'](), event[u'filename'])
                note = note_with_resources(note_title.encode('utf-8'), [resource],
                               self.cached_notebook, self.tags,
                               created=event.has_key(u'recv_date') and
                               1000*int(time.mktime(event[u'recv_date'].timetuple())))
                if not g_DRYRUN:
                    enNoteStore.createNote(enDevToken, note)
                return True
            except Errors.EDAMSystemException, e:
                if e.errorCode == Errors.EDAMErrorCode.RATE_LIMIT_REACHED:
                    wait_time = e.rateLimitDuration + 5
                    logger.warn(u'Evernote rate limit reached :-( '
                                u'Waiting %d seconds before retrying' %
                                (wait_time))
                    time.sleep(wait_time)
                    logger.debug(u'Finished waiting for rate limit reset.')
                
def save_wp_image_to_evernote(notebook_name, wp_image):
    # lookup existing WordPress image note
    note_title = u'%s <%s>' % (wp_image.filename, wp_image.id)
    
    pass


def main():
    for wp_image in wp_attachment_generator(457):
        save_wp_image_to_evernote('.zImages', wp_image)

if '__main__' == __name__:
    main()
