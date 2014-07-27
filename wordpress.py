#!/usr/bin/python
# -*- coding: utf-8 -*-

import urllib2
import re
import datetime

# WordPress API:
#import wordpress_xmlrpc
from wordpress_xmlrpc import Client #, WordPressPost
from wordpress_xmlrpc import WordPressPost as XmlRpcPost
from wordpress_xmlrpc import WordPressPage as XmlRpcPage
from wordpress_xmlrpc import WordPressMedia as XmlRpcMedia
#from wordpress_xmlrpc import WordPressPage as XmlRpcPage
from wordpress_xmlrpc.compat import xmlrpc_client
#from wordpress_xmlrpc.methods.posts import GetPosts, NewPost
#from wordpress_xmlrpc.methods.users import GetUserInfo
from wordpress_xmlrpc.methods import media, posts

import slugify

import common
from common import UrlParser

logger = common.logger.getChild('wordpress')

class WordPressAttribute(object):
    """WordPress item attribute."""
    
    @classmethod
    def create(cls, attr_name, value, wp_item):
        """Attribute factory method.
        
        Return a WordPress item attribute, initialized with `value`.
        """
        if attr_name in ('slug',):
            return WordPressSlugAttribute(value, wp_item)
        elif attr_name in ('last_modified', 'published_date'):
            return WordPressDateTimeAttribute(value, wp_item)
        else:
            return WordPressAttribute(value, wp_item)
    
    def __init__(self, value, wp_item, *args, **kwargs):
        """Initialize a basic WordPress attribute with plain string."""
        assert(isinstance(value, basestring))
        super(WordPressAttribute, self).__init__(*args, **kwargs)
        self.fset(value)
        self._wp_item = wp_item
    
    def fget(self):
        return self._value
    
    def fset(self, value):
        if isinstance(value, basestring):
            if '<auto>' == value.strip():
                self._value = None
                self._auto = True
            else:
                if value and value.isdigit():
                    value = int(value)
                self._value = value
                self._auto = False
        else:
            self._value = value
    
    def fdel(self):
        del self._value
    
    def str(self):
        """Return plain text representation of attribute value,
        safe to be used for serialization."""
        return str(self.fget())

class WordPressSlugAttribute(WordPressAttribute):
    """WordPress item slug attribute."""
    
    def fget(self):
        """Return slug string for item.
        
        If set to auto, and underlying item has title, then slugify the title.
        Otherwise return the string value for this attribute.
        """
        if self._auto and self._wp_item.title:
            return slugify.slugify(self._wp_item.title)
        else:
            return self._value

class WordPressDateTimeAttribute(WordPressAttribute):
    """WordPress date time attribute."""
    
    _format = '%Y-%m-%d %H:%M:%S'
    
    def __init__(self, value, wp_item, *args, **kwargs):
        """Initialize a DateTime WordPress attribute."""
        super(WordPressDateTimeAttribute, self).__init__(value, wp_item,
                                                         *args, **kwargs)
        self._auto = True
    
    def fset(self, value):
        """Set a DateTime attribute from string or from DateTime object."""
        if isinstance(value, datetime.datetime):
            self._value = value
        else:
            if '<auto>' == value.strip():
                self._value = None
            elif isinstance(value, basestring):
                self._value = datetime.datetime.strptime(value, self._format)
            else:
                self._value = value
    
    def str(self):
        if isinstance(self._value, datetime.datetime):
            return self._value.strftime(self._format)
        return str(self._value)

def wp_property(attr, default=None):
    """Return a WordPress property.
    
    Initialize the property with WordPressAttribute wrapper functions,
    to allow WordPressAttribute semnatics on the attribute instances,
    once they are initialized with such instances.
    """
    
    def fget(obj):
        """Return a WordPress attribute value.
        
        If the attribute was set to be a WordPressAttribute subclass,
        return the result of calling `fget()` on the attribute instance.
        Otherwise, simply return the attribute verbatim.
        
        :type obj: WordPressItem
        """
        if isinstance(obj._wp_attrs.get(attr), WordPressAttribute):
            return obj._wp_attrs[attr].fget()
        else:
            return obj._wp_attrs.get(attr, default)
    
    def fset(obj, value):
        """Set a WordPress attribute to `value`.
        
        If the attribute is already set to an instance of WordPressAttribute,
        and value is also an instance of WordPressAttribute, then replace it,
        but if value is not an instance of WordPressAttribute, then pass
        through the value to the `fset()` method of the attribute instance.
        """
        if isinstance(value, WordPressAttribute):
            obj._wp_attrs[attr] = value
        elif isinstance(obj._wp_attrs.get(attr), WordPressAttribute):
            obj._wp_attrs[attr].fset(value)
        else:
            obj._wp_attrs[attr] = value
    
    def fdel(obj):
        """Delete a WordPress attribute.
        
        If the attribute is an instance of WordPressAttribute,
        first call the `fdel()` method on the attribute instance.
        """
        if isinstance(obj._wp_attrs.get(attr), WordPressAttribute):
            obj._wp_attrs[attr].fdel()
        if attr in obj._wp_attrs:
            del obj._wp_attrs[attr]
    
    return property(fget, fset, fdel)

class WordPressItem(object):
    """Generic WordPress item class.
    Can be any of the specified `specialization` that has this as base class.
    """
    id = wp_property('id')
    title = wp_property('title')
    post_type = wp_property('post_type')
    content_format = wp_property('content_format')
    post_status = wp_property('post_status')
    categories = wp_property('categories', [])
    tags = wp_property('tags', [])
    slug = wp_property('slug')
    author = wp_property('author')
    content = wp_property('content')
    link = wp_property('link')
    parent = wp_property('parent')
    caption = wp_property('caption')
    published_date = wp_property('published_date')
    last_modified = wp_property('last_modified')
    description = wp_property('description')
    thumbnail = wp_property('thumbnail')
    project = wp_property('project')
    hemingway_grade = wp_property('hemingway_grade')
    seo_title = wp_property('seo_title')
    seo_description = wp_property('seo_description')
    seo_keywords = wp_property('seo_keywords', [])
    
    def set_wp_attribute(self, attr, value):
        """Set a WordPress attribute `attr` on this instance to `value`."""
        self._wp_attrs[attr] = value
    
    def __unicode__(self):
        return u'<%s: %s (%s)>' % (self.__class__.__name__,
                                   self.title, self.id)
    
    def __str__(self):
        return unicode(self).encode('utf-8')
    
    def __init__(self):
        # internal dictionary for WordPress attributes
        self._wp_attrs = dict()
        # A hashtable of WordPress items that the current item refers to
        #  (e.g. uses as images or links to other posts or pages)
        #  **not** including metadata fields (like thumbnail).
        # The table may contain actual WordPressItem-based instances,
        #  or callables that return WordPressItem-based instances when called
        #  with no arguments.
        # This allows late-loading items that may not be needed.
        # The key is not important - just used to avoid duplicate items.
        self._ref_wp_items = dict()
    
    @property
    def ref_items(self):
        # First yield the metadata items, if they are WordPressItems.
        for item in [self.thumbnail, self.parent, self.project]:
            if item and isinstance(item, WordPressItem):
                yield item
        # Then yield items referenced in the content, potentially late-loading
        #  them for the first time (and caching the results ofcourse).
        for k in self._ref_wp_items:
            item = self._ref_wp_items[k]
            if not isinstance(item, WordPressItem):
                item = item()
                assert(isinstance(item, WordPressItem))
                self._ref_wp_items[k] = item
            yield item
    
    def post_stub(self, wp_wrapper):
        """Post this WordPress item as a stub item, and update the ID.
        
        Uses specified `wp_wrapper` to interact with a WordPress site.
        
        :type wp_wrapper: WordPressApiWrapper
        """
        if self.id:
            raise RuntimeError('WordPress item has ID set.')
        self.upload_new_stub(wp_wrapper)
    
    def update_auto_attributes(self, wp_wrapper, xml_post):
        """Get the updated WordPress XML-RPC item and update auto fields.
        
        :type wp_wrapper: WordPressApiWrapper
        :param xml_post: An up-to-date XML-RPC post object to update from.
        :type xml_post: XmlRpcPost
        """
        # TODO: use attributes dictionary to do this automatically
        self.last_modified = xml_post.date_modified
        if 'publish' == xml_post.post_status and self.published_date is None:
            # first publish
            self.published_date = xml_post.date
        self.link = xml_post.link

class WordPressImageAttachment(WordPressItem):
    
    @classmethod
    def fromWpMediaItem(cls, wp_media_item):
        """Build a new ImageAttachment instance based on a XmlRpc Media object.
        
        :type wp_media_item: XmlRpcMedia
        """
        new_object = cls()
        mapping = [
            'id',
            'parent',
            'title',
            'description',
            'caption',
            'link',]
        for attr in mapping:
            setattr(new_object, attr, getattr(wp_media_item, attr))
        new_object._filename = UrlParser(wp_media_item.link).path_parts()[-1]
        new_object._get_image_data = lambda: urllib2.urlopen(new_object.link)
        return new_object
    
    def markdown_ref(self, context=None):
        if self.id:
            return ('[sb_easy_image ids="%d" size="medium" columns="1" '
                    'link="Lightbox"]' % (self.id))
#         if self.link and self.id:
#             imtag = '<a href="%s"><img src="%s" class="wp-image-%d" %s/>' \
#                 '</a>' % (self.link, self.link, self.id,
#                 self.description and 'alt="%s" ' % (self.description) or '')
#             if self.caption:
#                 return '[caption id="attachment_%d" align="alignnone"]%s %s' \
#                        '[/caption]' % (self.id, imtag, self.caption)
#             return imtag
    
    @property
    def image_data(self):
        """Image attachment binary data."""
        if hasattr(self, '_cached_image_data'):
            return self._cached_image_data
        if hasattr(self, '_get_image_data'):
            self._cached_image_data = self._get_image_data()
            return self._cached_image_data
        return self._image_data
    
    @property
    def mimetype(self):
        """Image attachment mimetype."""
        return self._image_mime
    
    @property
    def filename(self):
        """Image attachment filename."""
        return self._filename
    
    def upload_new_stub(self, wp_wrapper):
        """Post this WordPress image as a stub item, and update the ID.
        
        Uses specified `wp_wrapper` to interact with a WordPress site.
        Image item stub includes actual image, but not parent attachment.
        
        :type wp_wrapper: WordPressApiWrapper
        """
        data = {
            'name': self.filename,
            'type': self.mimetype,
            'bits': xmlrpc_client.Binary(self.image_data),
            }
        response = wp_wrapper.upload_file(data)
        self.id = int(response.get('id'))
        # update item attachment
        self.update_item(wp_wrapper)
    
    def update_item(self, wp_wrapper):
        """Update image attachment based on this instance.
        
        Use `wp_wrapper` to publish.
        
        @type wp_wrapper: WordPressApiWrapper
        @requires: Target note has no ID set.
        @raise RuntimeError: In case referenced WordPress items are missing
                             required fields (IDs / links or images etc.).
        """
        if self.id is None:
            raise RuntimeError('Cannot update image without ID set.')
        # The UploadFile method doesn't support setting parent ID, caption,
        # and description, so we need to get the uploaded image as post item
        # and edit it, remembering that internally Wordpress stores the
        # descripiton as "post_content" and the caption as "post_excerpt".
        # See also:
        # - https://core.trac.wordpress.org/ticket/18684
        # - https://core.trac.wordpress.org/ticket/21085
        # - https://core.trac.wordpress.org/ticket/13917
        # TODO: refactor to parent property
        as_post = wp_wrapper.get_post(self.id)
        as_post.title = self.title
        as_post.content = self.description
        as_post.excerpt = self.caption
        if self.parent and hasattr(self.parent, 'id'):
            as_post.parent_id = self.parent.id
        if not wp_wrapper.edit_post(as_post):
            raise RuntimeWarning('Failed setting parent ID to %d',
                                 self.parent.id)
        self.update_auto_attributes(wp_wrapper, as_post)

class WordPressPost(WordPressItem):

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
    
    @property
    def is_postable(self):
        """Return True if this item can be posted to a WordPress site."""
        for ref_item in self.ref_items:
            if ref_item.id is None:
                return False
        return True
    
    def markdown_ref(self, context=''):
        """Return a formatted link to be used in post content referring to
        this item, in Markdown format.
        
        If specified, `context` contains the original href element text,
        to allow custom processing.
        """
        func = re.match('\{\{[^\{\}\:]+\:(?P<func>\w+)\}\}', context)
        if func:
            func_name = func.groupdict()['func'].lower()
            if hasattr(self, func_name):
                return str(getattr(self, func_name))
            else:
                raise RuntimeError('Invalid functional modifier "%s" on item '
                                   '%s' % (func_name, self))
        if self.id:
            # TODO: title & context for anchor type link with text
            return '[post id="%d"]' % (self.id)
        if self.link:
            if self.title:
                return '%s "%s"' % (self.link, self.title.replace('"', ''))
            else:
                return self.link
    
    def _init_from_wp_post(self, wp_post):
        self.id = wp_post.id
        self.title = wp_post.title
        self.slug = wp_post.slug
        self.post_type = wp_post.post_type
        self.post_status = wp_post.post_status
        # TODO: bring categories, tags, author, thumbnail, content
        # TODO: bring hemingway-grade and content format custom fields
    
    def as_xml_rpc_obj(self, orig_post=None):
        """Return XML RPC WordPress item representation of this instance,
        with fields populated from the WP attributes of this instance.
        
        :param orig_post: Existing WordPress post for this instance.
        :type orig_post: XmlRpcPost
        """
        if orig_post:
            post = orig_post
        else:
            post = self.xml_rpc_object()
        
        def get_orig_custom_field(key):
            if hasattr(orig_post, 'custom_fields'):
                for field in orig_post.custom_fields:
                    if field['key'] == key:
                        return field
        def add_custom_field(post, key, val):
            if not hasattr(post, 'custom_fields'):
                post.custom_fields = list()
            custom_field = get_orig_custom_field(key)
            if custom_field:
                custom_field['value'] = val
            else:
                custom_field = {'key': key, 'value': val}
            post.custom_fields.append(custom_field)
        def add_terms(post, tax_name, terms_names):
            if not hasattr(post, 'terms_names'):
                post.terms_names = dict()
            post.terms_names[tax_name] = terms_names
        
        # TODO: let the fields represent themselves
        if self.id:
            post.id = self.id
        post.title = self.title
        post.content = self.content
        post.slug = self.slug
        post.post_status = self.post_status
        # TODO: author?
        if self.thumbnail and hasattr(self.thumbnail, 'id'):
            post.thumbnail = self.thumbnail.id
        if self.tags:
            add_terms(post, 'post_tag', self.tags)
        if self.categories:
            add_terms(post, 'category', self.categories)
        if (self.parent and hasattr(self.parent, 'id') and
            self.parent.id is not None):
            post.parent = self.parent.id
        if self.content_format:
            add_custom_field(post, 'content_format', self.content_format)
        if self.project and hasattr(self.project, 'id'):
            add_custom_field(post, 'project', self.project.id)
        if self.hemingway_grade:
            add_custom_field(post, 'hemingwayapp-grade', self.hemingway_grade)
        # SEO fields, assuming All-In-One SEO Pack plugin, with my special
        # protected-CF-exposing plugin to allow XML-RPC access to them.
        if self.seo_title:
            add_custom_field(post, '_aioseop_title', self.seo_title)
        if self.seo_description:
            add_custom_field(post, '_aioseop_description',
                             self.seo_description)
        if self.seo_keywords:
            add_custom_field(post, '_aioseop_keywords',
                             ','.join(self.seo_keywords))
        return post
    
    def xml_rpc_object(self):
        """Return a new XML-RPC object for this instance type."""
        if self.post_type in ('post',):
            return XmlRpcPost()
        elif self.post_type in ('page',):
            return XmlRpcPage()
        raise ValueError('Invalid post type "%s"', self.post_type)
    
    def upload_new_stub(self, wp_wrapper):
        """Post this WordPress post as a stub item, and update the ID.
        
        Uses specified `wp_wrapper` to interact with a WordPress site.
        
        :type wp_wrapper: WordPressApiWrapper
        """
        stub_post = self.xml_rpc_object()
        stub_post.title = self.title
        self.id = wp_wrapper.new_post(stub_post)
    
    def update_item(self, wp_wrapper):
        """Update post based on this instance.
        
        Use `wp_wrapper` to publish.
        
        @type wp_wrapper: WordPressApiWrapper
        @requires: Target note has no ID set.
        @raise RuntimeError: In case referenced WordPress items are missing
                             required fields (IDs / links or images etc.).
        """
        if self.id is None:
            raise RuntimeError('Cannot update post with no ID')
        if not self.is_postable:
            raise RuntimeError('Post instance not fully processed')
        xmlrpc_obj = self.as_xml_rpc_obj(wp_wrapper.get_post(self.id))
        if not wp_wrapper.edit_post(xmlrpc_obj):
            raise RuntimeError('Failed updating WordPress post')
        self.update_auto_attributes(wp_wrapper, wp_wrapper.get_post(self.id))

class WordPressApiWrapper(object):
    """WordPress client API wrapper class."""
    
    def __init__(self, xmlrpc_url, username, password):
        """Initialize WordPress client API wrapper.
        
        :param xmlrpc_url: Full URL to xmlrpc.php of target Wordpress site.
        :param username: Username to login to Wordpress site with API rights.
        :param password: Password to Wordpress account for user.
        """
        self._init_wp_client(xmlrpc_url, username, password)
    
    def _init_wp_client(self, xmlrpc_url, username, password):
        self._wp = Client(xmlrpc_url, username, password)
    
    def media_item_generator(self, parent_id=None):
        """Generates WordPress attachment objects."""
        for media_item in self._wp.call(media.GetMediaLibrary(
                            {'parent_id': parent_id and str(parent_id)})):
            wp_image = WordPressImageAttachment.fromWpMediaItem(media_item)
            logger.debug(u'Yielding WordPress media item %s', wp_image)
            yield wp_image
    
    def post_generator(self):
        """Generate WordPress post objects."""
        for post in self._wp.call(posts.GetPosts()):
            yield post
    
    def new_post(self, xmlrpc_post):
        """Wrapper for invoking the NewPost method."""
        return self._wp.call(posts.NewPost(xmlrpc_post))
    
    def get_post(self, post_id):
        """Wrapper for invoking the GetPost method."""
        return self._wp.call(posts.GetPost(post_id))
    
    def edit_post(self, xmlrpc_post):
        """Wrapper for invoking the EditPost method."""
        return self._wp.call(posts.EditPost(xmlrpc_post.id, xmlrpc_post))
    
    def upload_file(self, data):
        """Wrapper for invoking the upload file to the blog method."""
        return self._wp.call(media.UploadFile(data))
