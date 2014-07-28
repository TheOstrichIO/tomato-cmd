#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
import re
import argparse
from xml.etree import ElementTree as ET
import csv
from datetime import datetime

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
        if attr_name in ('categories', 'tags', 'seo_keywords'):
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
                # Add a late-loading function in case this will never be needed
                def load_item(link):
                    return lambda: self._adaptor.wp_item_from_note(link)
                self._wp_item._ref_wp_items[href] = load_item(href)
    
    @staticmethod
    def post_process_content_lines(content_lines):
        # ShellBot Easy Image post-processor:
        sbsc_re = re.compile(
            '\[sb_easy_image ids\=\"(?P<id>\d+)\" size\=\"medium\" '
            'columns\=\"1\" link\=\"Lightbox\"\]')
        # Markdown heading anchoring post-processor:
        mdha_re = re.compile(
            '(?P<hlevel>\#+)\s+(?P<htext>[^\#]+)\s+\#(?P<hanchor>[\w\-]+)')
        for num, line in enumerate(content_lines):
            # ShellBot Easy Image post-processor:
            matches = sbsc_re.findall(line)
            if 1 < len(matches):
                new_shortcode = ('[sb_easy_image ids="%s" size="medium" '
                                 'columns="%d" link="Lightbox"]' %
                                 (','.join(matches), len(matches)))
                content_lines[num] = re.sub('\[.*\]',
                                            new_shortcode,
                                            content_lines[num])
            # Markdown heading anchoring post-processor:
            match = mdha_re.match(line)
            if match:
                d = match.groupdict()
                content_lines[num] = '%s <a name="%s"></a>%s' % (d['hlevel'],
                                                                 d['hanchor'],
                                                                 d['htext'])
    
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
        self.post_process_content_lines(content_lines)
        self._cached_rendered_content = '\n'.join(content_lines)
        return self._cached_rendered_content
    
    def fget(self):
        """Return the rendered content."""
        # currently supporting only markdown rendering of content node
        assert('markdown' == self._wp_item.content_format)
        return self._render_node_as_markdown()

class EvernoteWordpressAdaptor(object):
    """Evernote-Wordpress Adaptor class."""
    
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
        return ET.fromstring(xml_string.replace(u'\xa0', u' ').encode('utf-8'),
                             parser=parser)
    
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
                return p
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
                p = ET.SubElement(get_active_node(), 'p')
                tail_p = append_tail(tail)
                return tail_p if tail_p is not None else p
            elif tag in ('en-note', 'div', 'p', 'br'):
                p = ET.SubElement(get_active_node(), 'p')
                if text:
                    p.text = text
                target_node = p
                for e in root:
                    next_target = parse_node(e, target_node)
                    if next_target is not None:
                        target_node = next_target
                tail_p = append_tail(tail)
                return tail_p if tail_p is not None else target_node
            elif tag in ('a', 'en-todo', 'en-media'):
                # Not expecting deeper levels!
                if 0 < len(root):
                    logger.warn('Skipping element with unexpected nested '
                                'elements: %s', ET.tostring(root))
                else:
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
                    return append_tail(tail)
            else:
                # Unexpected tag?
                logger.warn('Unexpected tag "%s"', root)
        # Start HERE
        # Cleanup DOM (regression of rogue <br /> in a-element)
        for bad_a in root.findall('.//a/br/..'):
            logger.warn('Removing rogue a-node with br-child (%s), '
                        'and inserting br-node instead', ET.tostring(bad_a))
            tail = bad_a.tail
            bad_a.clear()
            bad_a.tag = 'br'
            bad_a.tail = tail
        # Parse all sub elements of main en-note
        parse_node(root)
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
                    if 'metadata' != top_level_div.attrib['id']:
                        # in metadata div - don't allow empty p's!
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
            note = self.evernote.get_note(guid)
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
            def fetch_bits(guid, name):
                def fetch():
                    logger.debug('Fetching image %s', name)
                    return self.evernote.get_resource_data(guid)
                return fetch
            wp_item._get_image_data = fetch_bits(resource.guid, note.title)
            wp_item._image_mime = resource.mime
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
            attrs_to_update = {'id': str(wp_item.id),}
            if wp_item.link:
                attrs_to_update['link'] = str(wp_item.link)
            self.update_note_metdata(en_note, attrs_to_update)
    
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
        #: :type en_note: evernote.edam.type.ttypes.Note
        en_note = self.evernote.get_note(note_link)
        # Convert Evernote timestamp (ms from epoch) to DateTime object
        # (http://dev.evernote.com/doc/reference/Types.html#Typedef_Timestamp)
        note_updated = datetime.fromtimestamp(en_note.updated/1000)
        # Create a WordPress item from note
        #: :type wp_item: WordPressItem
        wp_item = self.wp_item_from_note(en_note)
        if (wp_item.last_modified is None or
            (wp_item.last_modified and note_updated > wp_item.last_modified)):
            # Post the item
            self.create_wordpress_stub_from_note(wp_item, en_note)
            for ref_wp_item in wp_item.ref_items:
                self.create_wordpress_stub_from_note(
                    ref_wp_item, ref_wp_item._underlying_en_note)
            wp_item.update_item(self.wordpress)
            # Update note metadata from published item (e.g. ID for new item)
            self.update_note_metadata_from_wordpress_post(en_note, wp_item)
        else:
            logger.info('Skipping posting note %s - not updated recently',
                        en_note.title)
    
    def sync(self, query):
        """Sync between WordPress site and notes matched by `query`.
        
        :param query: Evernote query used to find notes for sync.
        """
        for _, note in self.evernote.get_notes_by_query(query):
            logger.info('Posting note "%s" (GUID %s)', note.title, note.guid)
            try:
                self.post_to_wordpress_from_note(note.guid)
            except Exception:
                logger.exception('Failed posting note "%s" (GUID %s)',
                                 note.title, note.guid)
    
    def detach(self, query):
        """Detach sync between WordPress site and notes matched by `query`.
        
        :param query: Evernote query used to find notes to detach.
        """
        attrs_to_update = {'id': '<auto>',
                           'link': '<auto>',
                           'last_modified': '<auto>',
                           'published_date':  '<auto>',}
        for _, note_meta in self.evernote.get_notes_by_query(query):
            note = self.evernote.get_note(note_meta.guid,
                                         with_resource_data=False)
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
        global modified_flag
        modified_flag = False
        root = self._parse_xml_from_string(note.content)
        def update_node_text(orig_text):
            # Extract attribute name from element
            text = orig_text and orig_text.strip(' \n\r') or ''
            if not text:
                return orig_text
            if text.startswith('#'):
                return orig_text
            if '=' not in text:
                return orig_text
            pos = text.find('=')
            attr_name = text[:pos]
            # Update if needed
            if attr_name in attrs_to_update:
                current_val = text[pos+1:].strip(' \n\r')
                new_val = attrs_to_update[attr_name]
                if new_val == current_val:
                    logger.debug('No change in attribute "%s"', attr_name)
                else:
                    logger.debug('Changing note attribute "%s" from "%s" '
                                 'to "%s"', attr_name,
                                 current_val, new_val)
                    global modified_flag
                    modified_flag = True
                    return '%s=%s' % (attr_name, new_val)
            return orig_text
        for e in root.iter():
            if e.tag in ('hr', ):
                # <hr /> tag means end of metadata section
                break
            if e.tag in ('div', 'p', 'en-note',):
                e.text = update_node_text(e.text)
            e.tail = update_node_text(e.tail)
        # TODO: if metadata field doesn't exist - create one?
        if modified_flag:
            logger.info('Writing modified content back to note')
            note.content = '\n'.join([
                '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
                '<!DOCTYPE en-note SYSTEM '
                '"http://xml.evernote.com/pub/enml2.dtd">',
                ET.tostring(root)])
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
        attrs_to_update = {'id': str(item.id), }
        for attr in ['link', 'last_modified', 'published_date']:
            if (attr in item._wp_attrs and isinstance(item._wp_attrs[attr],
                                                      WordPressAttribute) and
                item._wp_attrs[attr].fget() is not None):
                attrs_to_update[attr] = item._wp_attrs[attr].str()
        self.update_note_metdata(note, attrs_to_update)
    
    def import_images_to_evernote(self, parent_id, notebook_name,
                                  set_id=None, set_parent=None):
        overrided_attrs = dict()
        if set_id:
            overrided_attrs['id'] = set_id
        if set_parent:
            overrided_attrs['parent'] = set_parent
        for wp_image in self.wordpress.media_item_generator(parent_id):
            save_wp_image_to_evernote(self.evernote, notebook_name, wp_image,
                                      overrides=overrided_attrs)

def save_wp_image_to_evernote(en_wrapper, notebook_name, wp_image,
                              force=False, overrides={}):
    # TODO: Do this better...
    #raise NotImplementedError("I'm broken")
    # lookup existing WordPress image note
    #note_title = u'%s <%s>' % (wp_image.filename, wp_image.id)
    #image_note = en_wrapper.getSingleNoteByTitle(note_title, notebook_name)
#     if not image_note or force:
    # prepare resource and note
    resource, resource_tag = en_wrapper.makeResource(wp_image.image_data,
                                                     wp_image.filename)
    note_content = ''
    for attr in ['id', 'title', 'link', 'parent', 'caption', 'description']:
        if attr in overrides:
            value = overrides[attr]
        else:
            value = getattr(wp_image, attr)
        note_content += '<div>%s=%s</div>\r\n' % (attr, value)
    note_content += '<hr/>\r\n%s' % (resource_tag)
    wp_image_note = en_wrapper.makeNote(title=wp_image.filename,
                                        content=note_content,
                                        resources=[resource])
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
    # create new note
    logger.info('Creating new WP Image note "%s"', wp_image.filename)
    en_wrapper.saveNoteToNotebook(wp_image_note, notebook_name)

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
sync_parser.set_defaults(func=lambda adaptor, args: adaptor.sync(args.query))

detach_parser = subparsers.add_parser('detach',
                                      help='Detach Evernote-WordPress '
                                           'synchronization')
detach_parser.add_argument('query',
                           help='Evernote query for notes to detach')
detach_parser.set_defaults(func=lambda adaptor, args:
                           adaptor.detach(args.query))

import_images_parser = subparsers.add_parser(
    'import-images',
    help='Import images attached to specified WordPress post into Evernote.')
import_images_parser.add_argument('--parent',
                                  help='Parent post.')
import_images_parser.add_argument('--notebook',
                                  help='Name of dest Evernote notebook.')
import_images_parser.add_argument('--set_id',
                                  help='Override ID value with this.')
import_images_parser.add_argument('--set_parent',
                                  help='Override parent value with this.')
import_images_parser.set_defaults(func=lambda adaptor, args:
                                  adaptor.import_images_to_evernote(
                                      args.parent, args.notebook,
                                      args.set_id, args.set_parent))

###############################################################################

def _custom_fields(adaptor, unused_args):
    for wp_post in adaptor.wordpress.post_generator():
        print wp_post, wp_post.custom_fields

def main():
    args = wp_en_parser.parse_args()
    adaptor = _get_adaptor(args)
    args.func(adaptor, args)

if '__main__' == __name__:
    main()
