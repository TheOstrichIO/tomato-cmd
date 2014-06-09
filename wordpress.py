#!/usr/bin/python
# -*- coding: utf-8 -*-

from xml.etree import ElementTree
import csv
import urllib2
import re

# WordPress API:
import wordpress_xmlrpc
from wordpress_xmlrpc import Client #, WordPressPost
from wordpress_xmlrpc import WordPressPost as XmlRpcPost
#from wordpress_xmlrpc.methods.posts import GetPosts, NewPost
#from wordpress_xmlrpc.methods.users import GetUserInfo
#from wordpress_xmlrpc.compat import xmlrpc_client
from wordpress_xmlrpc.methods import media, posts

import slugify

import common
from common import UrlParser
from my_evernote import EvernoteApiWrapper, note_link_re

logger = common.logger.getChild('wordpress')

class MetaWordPressItem(type):
    def __new__(cls, clsname, bases, dct):
        newclass = super(MetaWordPressItem, cls).__new__(cls, clsname,
                                                         bases, dct)
        for base in bases:
            if hasattr(base, 'register_specialization'):
                base.register_specialization(newclass)
        return newclass

class WordPressItem(object):
    """Generic WordPress item class.
    Can be any of the specified `specialization` that has this as base class.
    """
    __metaclass__ = MetaWordPressItem
    _specializations = list()
    _all_slots = set()
    _cache = dict()
    
    @classmethod
    def register_specialization(cls, subclass):
        cls._specializations.append(subclass)
        cls._all_slots.update(subclass._slots)
    
    @classmethod
    def _get_note_from_guid_or_enlink(cls, guid_or_enlink, en_wrapper=None):
        guid = guid_or_enlink
        if EvernoteApiWrapper.is_evernote_url(guid):
            guid = EvernoteApiWrapper.parseNoteLinkUrl(guid_or_enlink).guid
        if guid in cls._cache:
            return cls._cache[guid]
        assert(en_wrapper)
        note = en_wrapper.getNote(guid)
        cls._cache[guid] = note
        return note
    
    @classmethod
    def createFromEvernote(cls, note_or_guid_or_enlink, en_wrapper=None):
        note = note_or_guid_or_enlink
        if isinstance(note, basestring):
            guid = EvernoteApiWrapper.get_note_guid(note_or_guid_or_enlink)
        else:
            guid = note.guid
        # return parsed note from cache, if cached
        if guid in cls._cache:
            return cls._cache[guid]
        # not cached - parse and cache result
        if isinstance(note, str):
            assert(en_wrapper)
            note = en_wrapper.getNote(guid)
        parsed_item = cls()
        parsed_item.initFromEvernote(note)
        # Get item specialization
        for subclass in cls._specializations:
            if subclass.isInstance(parsed_item):
                # reinterpret cast
                parsed_item.__class__ = subclass
                break
        # process content Evernote links
        #  (put partial parsing in cache for recursive link processing!)
        cls._cache[guid] = parsed_item
        parsed_item.processLinks(en_wrapper)
        return parsed_item
            
    def __unicode__(self):
        return u'<%s: %s (%s)>' % (self.__class__.__name__,
                                   self.title, self.id)
    
    def __str__(self):
        return unicode(self).encode('utf-8')
    
    def __init__(self):
        for slot in self._all_slots:
            setattr(self, slot, None)
        self.content = ''
        self.tags = list()
        self.categories = list()
    
    def initFromEvernote(self, note):
        def fix_text(text):
            return text and text.strip('\n\r') or ''
        def parse_link(atag):
            # depends on content-format!
            # in markdown - web-links should parse to the a.text,
            #  and Evernote links should load the related WpImage
            # luckily - I don't want to support other formats...
            url = atag.attrib.get('href', '')
            if EvernoteApiWrapper.is_evernote_url(url):
                # surround in <> to allow secondary parsing
                return '<%s>' % (url)
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
                if line.startswith('#'):
                    # skipping commented lines in meta section
                    return
                match = re.match('(?P<key>[\w\-]+)\=(?P<value>.*)', line)
                if match:
                    k, v = match.groupdict()['key'], match.groupdict()['value']
                    if 'id' == k:
                        self.id = v.isdigit() and int(v) or None
                    elif 'type' == k:
                        # TODO: refactor getting list of types
                        assert(v in ('post', 'page', ))
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
                        v = v.strip('<>')
                        self.thumbnail = v
                    elif 'hemingwayapp-grade' == k:
                        self.hemingway_grade = v.isdigit() and int(v) or None
                    elif 'link' == k:
                        self.link = v <> '<auto>' and v or None
                    elif 'parent' == k:
                        v = v.strip('<>')
                        assert(EvernoteApiWrapper.is_evernote_url(v))
                        self.parent = v
                    elif 'project' == k:
                        # TODO: refactor field processing to something modular
                        # e.g., don't hardcode custom fields here...
                        v = v.strip('<>')
                        assert(EvernoteApiWrapper.is_evernote_url(v))
                        self.project = v
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
        ## Start here
        # Parse Evernote note content
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
    
    def publishItem(self, wp_wrapper):
        """Publish the WordPress item represented by this instance.
        Uses specified `wp_wrapper` to interact with a WordPress site.
        If instance has an ID, will try to update existing item with this ID.
        Otherwise, will create a new item and update relevant
        fields (like ID, link) on the instance.
        
        @raise RuntimeError: In case referenced WordPress items are missing
                                required fields (IDs / links or images etc.).
        @type wp_wrapper: WordPressApiWrapper
        """
        if self.id is None:
            self.publishNew(wp_wrapper)
        else:
            self.updateExisting(wp_wrapper)

class WordPressImageAttachment(WordPressItem):
    
    _slots = frozenset(('id', 'title', 'link', 'parent', 'caption',
                        'date_created', 'description')) # what's with alt?!
    
    @classmethod
    def isInstance(cls, instance):
        return (instance.post_type and instance.post_type in ('image',)) \
            or instance.post_type is None
    
    @classmethod
    def fromWpMediaItem(cls, wp_media_item):
        new_object = cls()
        new_object._init_from_wp_media_item(wp_media_item)
        return new_object
    
    def _init_from_wp_media_item(self, wp_media_item):
        for slot in self._slots:
            if not hasattr(wp_media_item, slot):
                logger.error('WordPress MediaItem "%s" has no attribute "%s"',
                             wp_media_item, slot)
                raise RuntimeError()
            self.__dict__[slot] = getattr(wp_media_item, slot)
        self.filename = UrlParser(self.link).path_parts()[-1]
    
    def formatContentLink(self):
        if self.link and self.id:
            imtag = '<a href="%s"><img src="%s" class="wp-image-%d" %s/>' \
                '</a>' % (self.link, self.link, self.id,
                self.description and 'alt="%s" ' % (self.description) or '')
            if self.caption:
                return '[caption id="attachment_%d" align="alignnone"]%s %s' \
                       '[/caption]' % (self.id, imtag, self.caption)
            return imtag
    
    def processLinks(self, en_wrapper=None):
        if EvernoteApiWrapper.is_evernote_url(self.parent):
            parent_item = WordPressItem.createFromEvernote(self.parent,
                                                           en_wrapper)
            if parent_item.id:
                self.parent = parent_item.id
            else:
                logger.warn('Parent item "%s" has no ID', parent_item)
    
    def image(self):
        "Returns a file-like object for reading image data."
        return urllib2.urlopen(self.link)
        # TODO: handle case of Evernote resource...

class WordPressPost(WordPressItem):
    _slots = frozenset(('id', 'title', 'slug', 'post_type', 'author', 'tags',
                        'post_status', 'content', 'categories', 'thumbnail',
                        # Custom fields
                        # TODO: refactor fields handling to be modular and
                        #       extensible, without hardcoded (custom) fields
                        'content_format', 'project', 'hemingway_grade',))
    
    @classmethod
    def isInstance(cls, instance):
        # TODO: refactor getting list of types
        return instance.post_type and instance.post_type in ('post', 'page', )
    
    @classmethod
    def fromWpPost(cls, wp_post):
        new_post = cls()
        new_post._init_from_wp_post(wp_post)
        return new_post
    
    def __init__(self):
        for slot in self._slots:
            setattr(self, slot, None)
        self.content = ''
        self.tags = list()
        self.categories = list()
        self._fully_processed_flag = False
    
    def get_slug(self):
        if self.slug:
            return self.slug
        elif self.title:
            return slugify.slugify(self.title)
    
    def isFullyProcessed(self):
        "True if all links and referenced items are valid"
        return self._fully_processed_flag
    
    def formatContentLink(self):
        if self.link:
            if self.title:
                return '%s "%s"' % (self.link, self.title.replace('"', ''))
            else:
                return self.link
    
    def processLinks(self, en_wrapper=None):
        def parse_content_link(match_obj):
            enlink = match_obj.group(1)
            item = WordPressItem.createFromEvernote(enlink, en_wrapper)
            link = item.formatContentLink()
            if link:
                return link
            else:
                logger.warn('Could not format content link for "%s"', item)
                self._fully_processed_flag = False
                return match_obj.group(0)
        self._fully_processed_flag = True
        # TODO: refactor fields processing such that the fields themselves
        #       define their processing (instead of hardcoding here)
        # parse thumbnail image link
        if (self.thumbnail and
                EvernoteApiWrapper.is_evernote_url(self.thumbnail)):
            self.thumbnail = WordPressItem.createFromEvernote(self.thumbnail,
                                                              en_wrapper)
        if self.thumbnail:
            if not isinstance(self.thumbnail, WordPressImageAttachment):
                self._fully_processed_flag = False
            elif not self.thumbnail.id:
                self._fully_processed_flag = False
        
        if self.project and EvernoteApiWrapper.is_evernote_url(self.project):
            self.project = WordPressItem.createFromEvernote(self.project,
                                                            en_wrapper)
        if self.project:
            if not isinstance(self.project, WordPressPost):
                self._fully_processed_flag = False
            elif not self.project.id:
                self._fully_processed_flag = False
        
        # replace all <evernote:///...> links within content
        # TODO: maybe match entire Markdown link?
        #  (so I don't override the title if it is specified)
        link_pattern = '\<(%s)\>' % (note_link_re.pattern)
        self.content = re.sub(link_pattern, parse_content_link, self.content)
    
    def _init_from_wp_post(self, wp_post):
        self.id = wp_post.id
        self.title = wp_post.title
        self.slug = wp_post.slug
        self.post_type = wp_post.post_type
        self.post_status = wp_post.post_status
        # TODO: bring categories, tags, author, thumbnail, content
        # TODO: bring hemingway-grade and content format custom fields
    
    def asXmlRpcPost(self):
        """Returns XML RPC WordPressPost item representation of this instance
        @rtype: wordpress_xmlrpc.WordPressPost
        """
        def add_custom_field(post, key, val):
            if not hasattr(post, 'custom_fields'):
                post.custom_fields = list()
            post.custom_fields.append({'key': key, 'value': val})
        def add_terms(post, tax_name, terms_names):
            if not hasattr(post, 'terms_names'):
                post.terms_names = dict()
            post.terms_names[tax_name] = terms_names
        post = XmlRpcPost()
        # TODO: let the fields represent themselves
        if self.id:
            post.id = self.id
        post.title = self.title
        post.content = self.content
        post.slug = self.get_slug()
        post.post_status = self.post_status
        # TODO: author?
        if self.thumbnail:
            post.thumbnail = self.thumbnail.id
        if self.tags:
            add_terms(post, 'post_tag', self.tags)
        if self.categories:
            add_terms(post, 'category', self.categories)
        if self.content_format:
            add_custom_field(post, 'content_format', self.content_format)
        if self.project:
            add_custom_field(post, 'project', self.project.id)
        if self.hemingway_grade:
            add_custom_field(post, 'hemingwayapp-grade', self.hemingway_grade)
        return post
    
    def publishNew(self, wp_wrapper):
        """Create new post based on this instance.
        Uses `wp_wrapper` to publish.
        
        @type wp_wrapper: WordPressApiWrapper
        @requires: Target note has no ID set - it will be populated.
        @raise RuntimeError: In case referenced WordPress items are missing
                                required fields (IDs / links or images etc.).
        """
        if self.id is not None:
            raise RuntimeError('Cannot publish new post when ID exists')
        if not self.isFullyProcessed():
            raise RuntimeError('Post instance not fully processed')
        if 'post' == self.post_type:
            xmlrpc_post = self.asXmlRpcPost()
        elif 'page' == self.post_type:
            xmlrpc_post = self.asXmlRpcPage()
        self.id = wp_wrapper.newPost(xmlrpc_post)
    
    def updateExisting(self, wp_wrapper):
        """Update existing post based on this instance.
        Uses `wp_wrapper` to publish.
        
        @type wp_wrapper: WordPressApiWrapper
        @requires: Target note has ID set.
        @raise RuntimeError: In case referenced WordPress items are missing
                                required fields (IDs / links or images etc.).
        """
        if self.id is None:
            raise RuntimeError('Cannot update post with no ID')
        if not self.isFullyProcessed():
            raise RuntimeError('Post instance not fully processed')
        if 'post' == self.post_type:
            xmlrpc_post = self.asXmlRpcPost()
        elif 'page' == self.post_type:
            xmlrpc_post = self.asXmlRpcPage()
        if not wp_wrapper.editPost(xmlrpc_post):
            raise RuntimeError('Failed updating WordPress post')

class WordPressApiWrapper(object):
    
    def __init__(self, xmlrpc_url, username, password):
        self._init_wp_client(xmlrpc_url, username, password)
    
    def _init_wp_client(self, xmlrpc_url, username, password):
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
    
    def newPost(self, xmlrpc_post):
        "Wrapper for invoking the NewPost method"
        return self._wp.call(posts.NewPost(xmlrpc_post))
    
    def editPost(self, xmlrpc_post):
        "Wrapper for invoking the EditPost method"
        return self._wp.call(posts.EditPost(xmlrpc_post.id, xmlrpc_post))
