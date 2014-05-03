#!/usr/bin/python
# -*- coding: utf-8 -*-

from xml.etree import ElementTree
import csv
import urllib2
import re

# WordPress API:
from wordpress_xmlrpc import Client #, WordPressPost
#from wordpress_xmlrpc.methods.posts import GetPosts, NewPost
#from wordpress_xmlrpc.methods.users import GetUserInfo
#from wordpress_xmlrpc.compat import xmlrpc_client
from wordpress_xmlrpc.methods import media, posts

import slugify

import common
from common import UrlParser

logger = common.logger.getChild('wordpress')

class WordPressImageAttachment():
    
    _slots = frozenset(('id', 'title', 'link', 'parent', 'caption',
                        'date_created', 'description'))
    
    @classmethod
    def fromWpMediaItem(cls, wp_media_item):
        new_object = cls()
        new_object._init_from_wp_media_item(wp_media_item)
        return new_object
    
    @classmethod
    def fromWpGenericItem(cls, wp_generic_item):
        new_object = cls()
        new_object._init_from_generic_wp_object(wp_generic_item)
        return new_object
    
    def _init_from_generic_wp_object(self, wp_generic_item):
        for slot in self._slots:
            if not hasattr(wp_generic_item, slot):
                logger.error('Generic WordPress object "%s" has no attribute '
                             '%s"', wp_generic_item, slot)
                raise RuntimeError()
            self.__dict__[slot] = getattr(wp_generic_item, slot)
        self.filename = self.link and UrlParser(self.link).path_parts()[-1]
    
    def _init_from_wp_media_item(self, wp_media_item):
        for slot in self._slots:
            if not hasattr(wp_media_item, slot):
                logger.error('WordPress MediaItem "%s" has no attribute "%s"',
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

class WordPressPost():
    _slots = frozenset(('id', 'title', 'slug', 'post_type',
                        'post_status', 'content_format', 'content',
                        'categories', 'tags', 'thumbnail', 'hemingway_grade'))
    
    @classmethod
    def fromWpPost(cls, wp_post):
        new_post = cls()
        new_post._init_from_wp_post(wp_post)
        return new_post
    
    @classmethod
    def fromWpGenericItem(cls, wp_generic_item):
        new_object = cls()
        new_object._init_from_generic_wp_object(wp_generic_item)
        return new_object
    
    def __init__(self):
        for slot in self._slots:
            setattr(self, slot, None)
        self.content = ''
        self.tags = list()
        self.categories = list()
    
    def get_slug(self):
        if self.slug:
            return self.slug
        elif self.title:
            return slugify.slugify(self.title)
    
    def _init_from_wp_post(self, wp_post):
        self.id = wp_post.id
        self.title = wp_post.title
        self.slug = wp_post.slug
        self.post_type = wp_post.post_type
        self.post_status = wp_post.post_status
        # TODO: bring categories, tags, author, thumbnail, content
        # TODO: bring hemingway-grade and content format custom fields
    
    def _init_from_generic_wp_object(self, wp_generic_item):
        for slot in self._slots:
            if not hasattr(wp_generic_item, slot):
                logger.error('Generic WordPress object "%s" has no attribute '
                             '%s"', wp_generic_item, slot)
                raise RuntimeError()
            self.__dict__[slot] = getattr(wp_generic_item, slot)

class GenericWordPressObject(object):
    _slots = WordPressImageAttachment._slots.union(WordPressPost._slots)
    
    def __init__(self, en_wrapper, note_guid):
        for slot in self._slots:
            setattr(self, slot, None)
        self.content = ''
        self.tags = list()
        self.categories = list()
        self._en_wrapper = en_wrapper
        self._note_guid = note_guid
    
    def fromEvernote(self):
        def fix_text(text):
            return text and text.lstrip('\n\r').rstrip(' \n\r\t') or ''
        def parse_link(atag):
            return atag.attrib['href']
            # depends on content-format!
            # in markdown - web-links should parse to the a.text,
            #  and Evernote links should load the related WpImage
            # luckily - I don't want to support other formats...
            href = atag.attrib.get('href', '')
            if href.startswith('evernote:///view/'):
                note_link = self._en_wrapper.parseNoteLinkUrl(href)
                return note_link
            else:
                return atag.text
        def parse_div(div):
            lines = [fix_text(div.text)]
            div_tail = fix_text(div.tail)
            for e in div:
                tail = fix_text(e.tail)
                if 'div' == e.tag:
                    if div_tail:
                        lines.append(div_tail)
                    return lines
                elif 'a' == e.tag:
                    lines[-1] += parse_link(e) + tail
                elif 'br' == e.tag:
                    lines.append(tail)
                elif e.tag in ('hr',):
                    pass
                elif 'en-todo' == e.tag:
                    logger.warn('Post still contains TODOs!')
                    lines[-1] += '&#x2751;' + tail
                else:
                    logger.warn('Don\'t know what to do with %s', repr(e))
            if div_tail:
                lines.append(div_tail)
            return lines
        def parse_list_value(value):
            # Handle stringed lists of the form:
            # in: 'val1,"val2", val3-hi, "val 4, quoted"'
            # out: ['val1', 'val2', 'val3-hi', 'val 4, quoted'] (4 items)
            return reduce(lambda x, y: x + y,
                          list(csv.reader([value], skipinitialspace=True)))
        def parse_line(line, in_meta):
            if in_meta:
                match = re.match('(?P<key>[\w\-]+)\=(?P<value>.*)', line)
                if match:
                    k, v = match.groupdict()['key'], match.groupdict()['value']
                    if 'id' == k:
                        self.id = v.isdigit() and int(v) or None
                    elif 'type' == k:
                        assert(v in ('post',))
                        self.post_type = v
                    elif 'content_format' == k:
                        assert(v in ('markdown', 'html',))
                        self.content_format = v
                    elif 'title' == k:
                        self.title = v
                    elif 'slug' == k:
                        self.slug = v <> '<auto>' and v or None
                    elif 'categories' == k:
                        self.categories = parse_list_value(v)
                    elif 'tags' == k:
                        self.tags = parse_list_value(v)
                    elif 'thumbnail' == k:
                        self.thumbnail = v
                    elif 'hemingwayapp-grade' == k:
                        self.hemingway_grade = v.isdigit() and int(v) or None
                    elif 'link' == k:
                        self.link = v <> '<auto>' and v or None
                    elif 'parent' == k:
                        assert(v.startswith('evernote:///view/'))
                        self.parent = v
                    elif 'caption' == k:
                        self.caption = v
                    elif 'date_created' == k:
                        self.date_created = v <> '<auto>' and v or None
                    elif 'description' == k:
                        self.description = v
                    else:
                        logger.warn('Unknown key "%s" (had value "%s")', k, v)
            else:
                self.content += line + '\n'
                if self.content.endswith('\n\n\n'):
                    self.content = self.content[:-1]
        # Start here
        note = self._en_wrapper.getNote(self._note_guid)
        root = ElementTree.fromstring(note.content)
        in_meta = True
        for e in root.iter():
            if 'hr' == e.tag:
                in_meta = False
            elif 'div' == e.tag:
                for line in parse_div(e):
                    parse_line(line, in_meta)
            elif e.tag in ('en-note', 'en-media', 'en-todo', 'a', 'br'):
                # en-note & en-media are not interesting
                # a & br & en-todo are always parsed higher up
                pass
            else:
                logger.warn('Unhandled tag "%s"', e)

def getWordPressObjectAttr(en_wrapper, note_link, expected_type, attr):
    wp_object = createWordPressObjectFromEvernoteNote(en_wrapper,
          en_wrapper.parseNoteLinkUrl(note_link).noteGuid, False)
    if not isinstance(wp_object, expected_type):
        logger.error('Object "%s" is not a %s object',
                     note_link, expected_type.__class__)
        raise RuntimeError()
    value = getattr(wp_object, attr)
    if value is None:
        logger.warn('Object "%s" has no ID.', wp_object)
        return note_link
    else:
        return value

def createWordPressObjectFromEvernoteNote(en_wrapper, note_guid,
                                          recursive=True):
    parsed_note = GenericWordPressObject(en_wrapper, note_guid)
    parsed_note.fromEvernote()
    if parsed_note.post_type and parsed_note.post_type in ('post',):
        # it's a post item
        wp_post = WordPressPost.fromWpGenericItem(parsed_note)
        if recursive:
            if wp_post.thumbnail.startswith('evernote:///view/'):
                # get image link from image post
                wp_post.thumbnail = getWordPressObjectAttr(en_wrapper,
                                                   wp_post.thumbnail,
                                                   WordPressImageAttachment,
                                                   'link')
            # TODO: repeat for content evernote:/// links
        return wp_post
    else:
        # it's an image item
        wp_image = WordPressImageAttachment.fromWpGenericItem(parsed_note)
        if recursive and isinstance(wp_image.parent, str) and \
                wp_image.parent.startswith('evernote:///view/'):
            # get ID from parent post
            wp_image.parent = getWordPressObjectAttr(en_wrapper,
                                                     wp_image.parent,
                                                     WordPressPost,
                                                     'id')
        return wp_image
            

class WordPressApiWrapper():
    
    def __init__(self, xmlrpc_url, username, password):
        self._wp = Client(xmlrpc_url, username, password)
    
    def mediaItemGenerator(self, parent_id=None):
        "Generates WordPress attachment objects."
        for media_item in self._wp.call(media.GetMediaLibrary(
                            {'parent_id': parent_id and str(parent_id)})):
            wpImage = WordPressImageAttachment.fromWpMediaItem(media_item)
            logger.debug(u'Yielding WordPress media item %s', wpImage)
            yield wpImage
    
    def postGenerator(self):
        "Generates WordPress post objects"
        for post in self._wp.call(posts.GetPosts()):
            yield post
