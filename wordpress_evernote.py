#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
import re
import argparse
from xml.etree import ElementTree as ET
import csv

import settings
import common
from wordpress import WordPressApiWrapper, WordPressPost, WordPressAttribute
from wordpress import WordPressItem, WordPressImageAttachment
from my_evernote import EvernoteApiWrapper
from __builtin__ import super

wp_en_parser = argparse.ArgumentParser(
    description='WordPress <--> Evernote utilities')
wp_en_parser.add_argument('--wordpress',
                          default='default',
                          help='WordPress account name to use from settings.')
subparsers = wp_en_parser.add_subparsers()

logger = common.logger.getChild('wordpress-evernote')

###############################################################################

class NoteParserError(Exception):
    pass

class WpEnAttribute(WordPressAttribute):
    """WordPress attribute from Evernote note."""
    
    @classmethod
    def create(cls, adaptor, attr_name, node, wp_item):
        """Attribute factory method.
         
        Return a WordPress item attribute for `attr_name`, initialized by
        node at root `node`.
        
        :type adaptor: EvernoteWordpressAdaptor
        :type node: xml.etree.ElementTree.Element
        :type wp_item: wordpress.WordPressItem
        """
        if attr_name in ('categories', 'tags'):
            return WpEnListAttribute(node.text, wp_item, adaptor)
        elif attr_name in ('parent', 'thumbnail', 'project'):
            return WpEnLinkAttribute(node, wp_item, adaptor)
        else:
            return WordPressAttribute.create(attr_name, node.text, wp_item)
    
    def __init__(self, value, wp_item, adaptor, *args, **kwargs):
        """Initialize WordPress attribute from Evernoten note."""
        super(WpEnAttribute, self).__init__(value, wp_item, *args, **kwargs)
        self._adaptor = adaptor

class WpEnListAttribute(WpEnAttribute):
    """WordPress item list attribute."""
    
    def __init__(self, value, wp_item, adaptor):
        """Initialize WordPress list attribute from Evernoten note.
        
        :type wp_item: wordpress.WordPressItem
        :type adaptor: EvernoteApiWrapper
        """
        super(WpEnListAttribute, self).__init__('', wp_item, adaptor)
        self._value = self._parse_values_from_string(value)
    
    @staticmethod
    def _parse_values_from_string(valstring):
        """Return list of value from valstring."""
        # Handle stringed lists of the form:
        # in: 'val1,"val2", val3-hi, "val 4, quoted"'
        # out: ['val1', 'val2', 'val3-hi', 'val 4, quoted'] (4 items)
        return reduce(lambda x, y: x + y,
                      list(csv.reader([valstring], skipinitialspace=True)))

class WpEnLinkAttribute(WpEnAttribute):
    """WordPress item link attribute."""
    
    def __init__(self, node, wp_item, adaptor):
        """Initialize WordPress link attribute from Evernoten note.
        
        The node is expected to contain only a link tag (a href).
        
        :type node: xml.etree.ElementTree.Element
        :type wp_item: wordpress.WordPressItem
        :type adaptor: EvernoteApiWrapper
        """
        if '' != node.text:
            raise NoteParserError('Link "%s" should not have text' %
                                  (ET.tostring(node)))
        if not (node.tail is None or '' == node.tail):
            raise NoteParserError('Link "%s" should not have tail' %
                                  (ET.tostring(node)))
        if 0 == len(node):
            logger.warn('No link found for attribute')
            self._href = None
            super(WpEnLinkAttribute, self).__init__('', wp_item, adaptor)
            return
        if 1 != len(node):
            raise NoteParserError('Link "%s" should have one child' %
                                  (ET.tostring(node)))
        a_node = node[0]
        if 'a' != a_node.tag:
            raise NoteParserError('Link "%s" should have one <a> child' %
                                  (ET.tostring(node)))
        if not (a_node.tail is None or '' == a_node.tail):
            raise NoteParserError('Link "%s" should not have tail' %
                                  (ET.tostring(a_node)))
        self._href = a_node.get('href')
        if not self._href:
            raise NoteParserError('Link "%s" has no href' %
                                  (ET.tostring(a_node)))
        self._text = a_node.text
        self._ref_item = None
        super(WpEnLinkAttribute, self).__init__(self._href, wp_item, adaptor)
    
    def fget(self):
        if EvernoteApiWrapper.is_evernote_url(self._href):
            if self._ref_item is None:
                self._ref_item = self._adaptor.wp_item_from_note(self._href)
            return self._ref_item
        else:
            return self._href

class WpEnContent(WpEnAttribute):
    """WordPress content attribute from Evernote note."""
    
    def __init__(self, node, wp_item, adaptor):
        """Initialize WordPress content attribute from Evernoten note.
        
        Do not render the content on initialization, only on read.
        Do scan the a-tags in the content and update the underlying item
         ref-items list.
        
        :type node: xml.etree.ElementTree.Element
        :type wp_item: wordpress.WordPressItem
        :type adaptor: EvernoteApiWrapper
        """
        super(WpEnContent, self).__init__('', wp_item, adaptor)
        self._cached_rendered_content = None
        self._content_node = node
        self._find_ref_items()
    
    def _find_ref_items(self):
        for a_tag in self._content_node.findall('.//a'):
            href = a_tag.get('href', '')
            if EvernoteApiWrapper.is_evernote_url(href):
                ref_item = self._adaptor.wp_item_from_note(href)
                self._wp_item._ref_wp_items.add(ref_item)
    
    def _render_node_as_markdown(self):
        if self._cached_rendered_content:
            return self._cached_rendered_content
        
        def render_line_element(e, line_so_far):
            tag = e.tag.lower()
            if 'a' == tag:
                href = e.get('href', '')
                text = e.text
                if EvernoteApiWrapper.is_evernote_url(href):
                    ref_item = self._adaptor.wp_item_from_note(href)
                    return ref_item.markdown_ref(text)
                else:
                    return href
            elif 'span' == tag:
                return e.text
            elif 'en-todo' == tag:
                return '&#x2751;'
            elif 'en-media' == tag:
                logger.warn('Unexpected en-media element in content: %s',
                            ET.tostring(e))
                return ''
            else:
                raise NoteParserError('Invalid tag "%s" in content paragraph' %
                                      (ET.tostring(e)))
        content_lines = list()
        # Render content using DFS iteration of node
        for p in self._content_node:
            # Content node is expected to contain only p-tags, one per line.
            assert('p' == p.tag.lower())
            assert(p.tail is None)
            line = p.text or ''
            for e in p:
                line += render_line_element(e, line) or ''
                line += e.tail or ''
            content_lines.append(line)
        self._cached_rendered_content = '\n'.join(content_lines)
        return self._cached_rendered_content
    
    def fget(self):
        """Return the rendered content."""
        # currently supporting only markdown rendering of content node
        assert('markdown' == self._wp_item.content_format)
        return self._render_node_as_markdown()

class EvernoteWordpressAdaptor(object):
    """Evernote-Wordpress Adaptor class."""
    
    _attr_pattern = ('(\A|\s*\<\w+\>)\s*(?P<attr>{attr_name}\s*\=\s*'
                    '(?P<value>[\w\&\;]+))\s*(\Z|\<\/\w+\>\s*)')
    _attr_matchers_cache = dict()
    _hr_matcher = re.compile('\<hr\s*\/?\>', re.IGNORECASE)
    
    @classmethod
    def _get_attr_matcher(cls, attr_name):
        """Return a compiled RegEx matcher for metadata attributes"""
        if attr_name in cls._attr_matchers_cache:
            return cls._attr_matchers_cache[attr_name]
        # RegEx for finding metadata attributes
        # - <attr-name> in beginning of line or immediately following <..> tag
        # - "=" after <attr-name>, optionally with whitespaces around it
        # - <value> after the "=" up to end of line or closing </..> tag,
        #   where value may contain alphanumeric, "&", or ";".
        matcher = re.compile(cls._attr_pattern.format(attr_name=attr_name),
                             re.IGNORECASE)
        cls._attr_matchers_cache[attr_name] = matcher
        return matcher
    
    @staticmethod
    def _parse_xml_from_string(xml_string):
        """Return parsed ElementTree from xml_string."""
        parser = ET.XMLParser()
        # Default XMLParser is not full XHTML, so it doesn't know about all
        # valid XHTML entities (such as &nbsp;), so the following code is
        # needed in order to allow these entities.
        # (see: http://stackoverflow.com/questions/7237466 and
        #       http://stackoverflow.com/questions/14744945 )
        # Valid XML entities: quot, amp, apos, lt and gt.
        parser.parser.UseForeignDTD(True)
        parser.entity['nbsp'] = ' '
        return ET.fromstring(xml_string, parser=parser)
    
    @staticmethod
    def _parse_note_xml(note_content):
        """Return a normalized Element tree root from note content XML string.
        
        A normalized WordPress item note is as follows:
        1. Root `en-note` element.
        1.1. `div` node with id `metadata`
        1.1.1. A `p` node for every metadata attribute, of the form
               `attr_key=attr_value`, where `attr_key` is a string and
               `attr_value` may contain string or `a` node.
        1.2. `div` node with id `content`
        1.2.1. `p` node for every content paragraph, containing text and/or
               `a` nodes.
        """
        root = EvernoteWordpressAdaptor._parse_xml_from_string(note_content)
        norm_root = ET.Element('en-note')
        norm_meta = ET.SubElement(norm_root, 'div', id='metadata')
        norm_content = ET.SubElement(norm_root, 'div', id='content')
        global stage
        stage = 'meta'
        def fix_text(text):
            return text and text.strip('\n\r') or ''
        def get_active_node():
            if 'meta' == stage:
                return norm_meta
            elif 'content' == stage:
                return norm_content
            else:
                raise NoteParserError('Invalid stage "%s"' % (stage))
        def append_tail(text):
            if text:
                p = ET.SubElement(get_active_node(), 'p')
                p.text = text
        def parse_node(root, target_node=None):
            tag = root.tag.lower()
            text = fix_text(root.text)
            tail = fix_text(root.tail)
            if tag in ('hr', ):
                # End of metadata section
                assert(not root.text and (0 == len(root)))
                global stage
                if 'meta' == stage:
                    stage = 'content'
                else:
                    raise NoteParserError('Invalid stage "%s"' % (stage))
                append_tail(tail)
            elif tag in ('div', 'p', 'br'):
                p = ET.SubElement(get_active_node(), 'p')
                if text:
                    p.text = text
                for e in root:
                    parse_node(e, p)
                append_tail(tail)
            elif tag in ('a', 'en-todo', 'en-media'):
                # Not expecting deeper levels!
                if 0 < len(root):
                    logger.warn('Skipping element with unexpected nested '
                                'elements: %s', ET.tostring(root))
                else:
                    #assert(0 == len(root))
                    child = ET.SubElement(
                        target_node if target_node is not None
                        else ET.SubElement(get_active_node(), 'p'),
                        tag)
                    if root.get('href'):
                        child.set('href', root.get('href'))
                    if text:
                        child.text = text
                    if tail:
                        child.tail = tail
            elif tag in ('span',):
                # Treat span like it simply isn't there...
                if text:
                    if target_node is None:
                        logger.warn('Don\'t know what to do with text in '
                                    'top level span element: %s',
                                    ET.tostring(root))
                    else:
                        target_node.text += text
                for e in root:
                    parse_node(e, target_node)
                if tail:
                    logger.warn('Guessing how to append tail of span element: '
                                '%s', ET.tostring(root))
                    append_tail(tail)
            else:
                # Unexpected tag?
                logger.warn('Unexpected tag "%s"', root)
        # Parse all sub elements of main en-note
        for e in root:
            parse_node(e)
        # Clean up redundant empty p tags in normalized tree
        for top_level_div in norm_root:
            del_list = list()
            trailing_empty_list = list()
            prev_empty = True # initialized to True to remove prefix empty p's
            for p in top_level_div:
                # sanity - top level divs should contain only p elements
                assert('p' == p.tag)
                assert(not p.tail)
                if (p.text or 0 < len(p)):
                    prev_empty = False
                    trailing_empty_list = list()
                else:
                    # Empty p - only one is allowed in between non-empty p's
                    if prev_empty:
                        del_list.append(p)
                    else:
                        trailing_empty_list.append(p)
                    prev_empty = True
            for p in del_list + trailing_empty_list:
                top_level_div.remove(p)
        return norm_root
    
    def __init__(self, en_wrapper, wp_wrapper):
        """Initialize Adaptor instance with API wrapper objects.
        
        :param en_wrapper: Initialized Evernote API wrapper instance.
        :type en_wrapper: my_evernote.EvernoteApiWrapper
        :param wp_wrapper: Initialized Wordpress API wrapper instance.
        :type wp_wrapper: wordpress.WordPressApiWrapper
        """
        self.evernote = en_wrapper
        self.wordpress = wp_wrapper
        self.cache = dict()
    
    def wp_item_from_note(self, note_link):
        """Factory builder of WordPressItem from Evernote note.
        
        :param note_link: Evernote note link string for note to create.
        """
        if isinstance(note_link, basestring):
            guid = EvernoteApiWrapper.get_note_guid(note_link)
        else:
            note = note_link
            guid = note.guid
        # return parsed note from cache, if cached
        if guid in self.cache:
            return self.cache[guid]
        # not cached - parse and cache result
        if isinstance(note_link, basestring):
            note = self.evernote.getNote(guid)
        wp_item = WordPressItem()
        wp_item._underlying_en_note = note
        self.cache[guid] = wp_item
        item_dom = self._parse_note_xml(note.content)
        # Copy metadata fields to wp_item internal fields
        # Convert from Evernote attribute name to internal name if needed
        name_mappings = {
            'type': 'post_type',
            'hemingwayapp-grade': 'hemingway_grade',
        }
        for metadata in item_dom.findall(".//div[@id='metadata']/p"):
            if metadata.text is None:
                continue
            if metadata.text.startswith('#'):
                continue
            pos = metadata.text.find('=')
            attr_name = metadata.text[:pos]
            attr_name = name_mappings.get(attr_name, attr_name)
            metadata.text = metadata.text[pos+1:]
            wp_item.set_wp_attribute(attr_name,
                                     WpEnAttribute.create(self, attr_name,
                                                          metadata, wp_item))
        # Determine post type and continue initialization accordingly
        if wp_item.post_type in ('post', 'page'):
            # Initialize as WordPress post, and set content
            wp_item.__class__ = WordPressPost
            wp_item.set_wp_attribute(
                'content', WpEnContent(item_dom.find(".//div[@id='content']"),
                                       wp_item, self))
        else:
            # Initialize as WordPress image attachment, and fetch image
            wp_item.__class__ = WordPressImageAttachment
            wp_item._filename = note.title
            if not note.resources or 0 == len(note.resources):
                raise NoteParserError('Note (%s) has no attached resources' %
                                      (note.title))
            resource = note.resources[0]
            if 1 < len(note.resources):
                logger.warning('Note has too many attached resources (%d). '
                               'Choosing the first one, arbitrarily.',
                               len(note.resources))
            wp_item._image_data = resource.data.body
            wp_item._image_mime = resource.mime
            logger.debug('Got image with mimetype %s', wp_item.mimetype)
        return wp_item
    
    def create_wordpress_stub_from_note(self, wp_item, en_note):
        """Create WordPress item stub from item with no ID.
        
        The purpose is the create an ID without publishing all related items.
        The created ID will be updated in the Evernote note.
        The item will be posted as a draft in WordPress.
        
        :param `note_link`: Evernote note link string for
                            note with item to publish.
        """
        if not wp_item.id:
            # New WordPress item
            # Post as stub in order to get ID
            wp_item.post_stub(self.wordpress)
            assert(wp_item.id)
            # Update ID in note
            self.update_note_metdata(en_note, {'id': str(wp_item.id), })
    
    def post_to_wordpress_from_note(self, note_link):
        """Create WordPress item from Evernote note,
        and publish it to a WordPress blog.
        
        A note with ID not set will be posted as a new item, and the assigned
         item ID will be updated in the Evernote note.
        A note with ID set will result an update of the existing item.
        
        @warning: Avoid posting the same note to different WordPress accounts,
                  as the IDs might be inconsistent!
        
        :param note_link: Evernote note link string for
                            note with item to publish.
        """
        # Get note from Evernote
        en_note = self.evernote.getNote(note_link)
        # Create a WordPress item from note
        #: :type wp_item: WordPressItem
        wp_item = self.wp_item_from_note(en_note)
        # Post the item
        self.create_wordpress_stub_from_note(wp_item, en_note)
        for ref_wp_item in wp_item.ref_items:
            self.create_wordpress_stub_from_note(
                ref_wp_item, ref_wp_item._underlying_en_note)
        wp_item.update_item(self.wordpress)
        # Update note metadata from published item (e.g. ID for new item)
        self.update_note_metadata_from_wordpress_post(en_note, wp_item)
    
    def sync(self, query):
        """Sync between WordPress site and notes matched by `query`.
        
        :param query: Evernote query used to find notes for sync.
        """
        for _, note in self.evernote.get_notes_by_query(query):
            logger.info('Posting note "%s" (GUID %s)', note.title, note.guid)
            try:
                self.post_to_wordpress_from_note(note.guid)
            except RuntimeError:
                logger.exception('Failed posting note "%s" (GUID %s)',
                                 note.title, note.guid)
    
    def detach(self, query):
        """Detach sync between WordPress site and notes matched by `query`.
        
        :param query: Evernote query used to find notes to detach.
        """
        attrs_to_update = {'id': '&lt;auto&gt;', 'link': '&lt;auto&gt;', }
        for _, note_meta in self.evernote.get_notes_by_query(query):
            note = self.evernote.getNote(note_meta.guid)
            logger.info('Detaching note "%s" (GUID %s)', note.title, note.guid)
            self.update_note_metdata(note, attrs_to_update)
    
    def update_note_metdata(self, note, attrs_to_update):
        """Updates an Evernote WP-item note metadata based on dictionary.
        
        For every key in `attrs_to_update`, update the metadata attribute `key`
        with new value `attrs_to_update[key]`.
        
        :param note: Evernote post-note to update.
        :type note: evernote.edam.type.ttypes.Note
        :param attrs_to_update: Dictionary of attributes to update.
        :type attrs_to_update: dict
        """
        modified_flag = False
        content_lines = note.content.split('\n')
        for linenum, line in enumerate(content_lines):
            if self._hr_matcher.search(line):
                # <hr /> tag means end of metadata section
                break
            for attr, new_val in attrs_to_update.iteritems():
                m = self._get_attr_matcher(attr).match(line)
                if m:
                    current_val = m.groupdict()['value']
                    if new_val == current_val:
                        logger.debug('No change in attribute "%s"', attr)
                    else:
                        logger.debug('Changing note attribute "%s" from "%s" '
                                     'to "%s"', attr, current_val, new_val)
                        attr_str = m.groupdict()['attr']
                        content_lines[linenum] = line.replace(
                            attr_str, '%s=%s' % (attr, new_val))
                        modified_flag = True
        # TODO: if metadata field doesn't exist - create one?
        if modified_flag:
            logger.info('Writing modified content back to note')
            note.content = '\n'.join(content_lines)
            self.evernote.updateNote(note)
        else:
            logger.info('No changes to note content')
    
    def update_note_metadata_from_wordpress_post(self, note, item):
        """Updates an Evernote WP-item note metadata based on Wordpress item.
        
        Updates only fields that has WordPress as the authoritative source,
        like ID & link.
        
        :requires: `item` was originally constructed from `note`.
        
        :param note: Evernote post-note to update
        :type note: evernote.edam.type.ttypes.Note
        :param item: Wordpress item from which to update
        :type item: wordpress.WordPressItem
        
        Exceptions:
         :raise RuntimeError: If ID is set and differs
        """
        # TODO: get authoritative attributes from WordPress class
        attrs_to_update = {'id': str(item.id), } #('link', post.link),)
        self.update_note_metdata(note, attrs_to_update)

def save_wp_image_to_evernote(en_wrapper, notebook_name, wp_image,
                              force=False):
    raise NotImplementedError("I'm broken")
    # lookup existing WordPress image note
    #note_title = u'%s <%s>' % (wp_image.filename, wp_image.id)
    #image_note = en_wrapper.getSingleNoteByTitle(note_title, notebook_name)
#     if not image_note or force:
#         # prepare resource and note
#         resource, resource_tag = en_wrapper.makeResource(wp_image.image(),
#                                                          wp_image.filename)
#         note_content = '%s\r\n<hr/>\r\n' % (resource_tag)
#         for attr in WordPressImageAttachment._slots:
#             note_content += '<div>%s=%s</div>\r\n' % (attr,
#                                                       getattr(wp_image, attr))
#         wp_image_note = en_wrapper.makeNote(title=note_title,
#                                             content=note_content,
#                                             resources=[resource])
#     if image_note:
#         # note exists
#         logger.info('WP Image note "%s" exists in Evernote', note_title)
#         if force:
#             logger.info('Updating note with WordPress version.')
#             # update existing note with overwritten content
#             wp_image_note.guid = image_note.guid
#             en_wrapper.updateNote(wp_image_note)
#         else:
#             logger.debug('Skipping note update')
#     else:
#         # create new note
#         logger.info('Creating new WP Image note "%s"', note_title)
#         en_wrapper.saveNoteToNotebook(wp_image_note, notebook_name)

###############################################################################

def _get_adaptor(args):
    wp_account = settings.WORDPRESS[args.wordpress]
    # Each entry can be either a WordPressCredentials object,
    # or a name of another entry.
    while not isinstance(wp_account, settings.WordPressCredentials):
        wp_account = settings.WORDPRESS[wp_account]
    logger.debug('Working with WordPress at URL "%s"', wp_account.xmlrpc_url)
    wp_wrapper = WordPressApiWrapper(wp_account.xmlrpc_url,
                                     wp_account.username, wp_account.password)
    en_wrapper = EvernoteApiWrapper(settings.enDevToken_PRODUCTION)
    return EvernoteWordpressAdaptor(en_wrapper, wp_wrapper)

def post_note(adaptor, args):
    """ArgParse handler for post-note command."""
    adaptor.post_to_wordpress_from_note(args.en_link)

post_parser = subparsers.add_parser('post-note',
                                    help='Create a WordPress post from '
                                         'Evernote note')
post_parser.add_argument('en_link',
                         help='Evernote note to post '
                              '(full link, or just GUID)')
post_parser.set_defaults(func=post_note)

sync_parser = subparsers.add_parser('sync',
                                    help='Synchronize Evernote-WordPress')
sync_parser.add_argument('query',
                         help='Evernote query for notes to sync')
sync_parser.set_defaults(func=lambda  adaptor, args: adaptor.sync(args.query))

detach_parser = subparsers.add_parser('detach',
                                      help='Detach Evernote-WordPress '
                                           'synchronization')
detach_parser.add_argument('query',
                           help='Evernote query for notes to detach')
detach_parser.set_defaults(func=lambda  adaptor, args:
                           adaptor.detach(args.query))

###############################################################################

def _images_to_evernote(adaptor, unused_args):
    for wp_image in adaptor.wordpress.media_item_generator():
        save_wp_image_to_evernote(adaptor.evernote, '.zImages', wp_image)

def _custom_fields(adaptor, unused_args):
    for wp_post in adaptor.wordpress.post_generator():
        print wp_post, wp_post.custom_fields

def main():
    args = wp_en_parser.parse_args()
    adaptor = _get_adaptor(args)
    #_images_to_evernote(adaptor, args)
    args.func(adaptor, args)

if '__main__' == __name__:
    main()
