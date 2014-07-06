import unittest
from mock import patch, Mock, MagicMock, call
import os
from datetime import datetime

import wordpress
import wordpress_evernote
from wordpress import WordPressPost, WordPressImageAttachment
from wordpress import WordPressApiWrapper
from my_evernote import EvernoteApiWrapper
from wordpress_evernote import EvernoteWordpressAdaptor

from collections import namedtuple

EvernoteNotebook = namedtuple('EvernoteNotebook', ['guid', 'name'])

class EvernoteNote(object):
    """Dummy Evernote Note class for mocking note object in unit tests."""
    def __init__(self, **kwargs):
        self.resources = list()
        for k, v in kwargs.iteritems():
            setattr(self, k, v)
        if 'content' in kwargs:
            if self.content.lower().endswith('.xml'):
                # it's a test-data filename, not actual content
                self.content = self._get_content(self.content)
        if 'updated' not in kwargs:
            self.updated = 1404308967000
            
    def _get_content(self, fname):
        fpath = os.path.join('test-data', 'notes-content', fname)
        with open(fpath, 'r') as note_file:
            return note_file.read()

class WordpressXmlRpcItem(object):
    """Dummy Wordpress XML-RPC class for mocking in unit tests."""
    def __init__(self, **kwargs):
        self.resources = list()
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

test_notebooks = [
    EvernoteNotebook('abcd1234-5678-abef-7890-abcd1234abcd', 'Blog Posts'),
    EvernoteNotebook('abcd1234-5678-cdef-7890-abcd1234abcd', 'Blog Images'),
    ]

test_notes = {
    'note-with-id-thumbnail-attached-image-body-link':
    EvernoteNote(
        guid='abcd1234-5678-abcd-7890-abcd1234abcd',
        title='Test post note',
        notebookGuid='abcd1234-5678-abef-7890-abcd1234abcd',
        content='note-1.xml'),
    'image-with-id':
    EvernoteNote(
        guid='abcd1234-1234-abcd-1234-abcd1234abcd',
        title='test.png',
        notebookGuid='abcd1234-5678-cdef-7890-abcd1234abcd',
        content='image-with-id.xml',
        resources=[MagicMock()]),
    'project-page-with-id-nothumb':
    EvernoteNote(
        guid='abcd1234-aaaa-0000-ffff-abcd1234abcd',
        title='Test project index page',
        notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
        content='project-page-1.xml'),
    'project-note-with-id-nothumb':
    EvernoteNote(
        guid='abcd1234-5678-0000-7890-abcd1234abcd',
        title='Another test note',
        notebookGuid='abcd1234-5678-abef-7890-abcd1234abcd',
        content='project-note-1.xml'),
    'project-note-noid':
    EvernoteNote(
        guid='abcd1234-aaaa-2048-ffff-abcd1234abcd',
        title='New project note',
        notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
        content='project-note-2.xml'),
    'image-noid-existing-parent':
    EvernoteNote(
        guid='abcd1234-1212-4040-2121-abcd1234abcd',
        title='new-image.png',
        notebookGuid='abcd1234-5678-cdef-7890-abcd1234abcd',
        content='image-no-id.xml',
        resources=[MagicMock()]),
    'regression-projpage-a-br':
    EvernoteNote(
        guid='aaff0101-4343-abac-9898-aaaaeeeecccc',
        title='The Ostrich Website project page',
        notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
        content='regression-projpage-a-br.xml'),
    'regression-projnote-span-br':
    EvernoteNote(
        guid='aaff0101-2048-abac-4096-aaaaeeeecccc',
        title='The Ostrich note',
        notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
        content='regression-projnote-span-br.xml'),
    }

def mocked_get_note(guid):
    for note in test_notes.values():
        if note.guid == guid:
            return note

class TestEvernoteWordPressParser(unittest.TestCase):
    
    @patch('my_evernote.EvernoteApiWrapper._init_en_client')
    def setUp(self, mock_init_en_client):
        wordpress.logger = Mock()
        wordpress_evernote.logger = Mock()
        self.evernote = EvernoteApiWrapper(token='123')
        self.evernote.getNote = MagicMock(side_effect=mocked_get_note)
        self.adaptor = EvernoteWordpressAdaptor(self.evernote, None)
    
    def assertElementTreeEqual(self, root1, root2, msg=None):
        """Helper method to compare ElementTree objects."""
        def norm_text(text):
            if text is None:
                return ''
            return text.strip('\n\r')
        self.assertEqual(root1.tag, root2.tag, msg)
        self.assertEqual(norm_text(root1.text), norm_text(root2.text), msg)
        self.assertEqual(norm_text(root1.tail), norm_text(root2.tail), msg)
        self.assertDictEqual(root1.attrib, root2.attrib, msg)
        self.assertEqual(len(root1), len(root2), msg)
        for e1, e2 in zip(root1, root2):
            self.assertElementTreeEqual(e1, e2, msg)
    
    def test_evernote_wpitem_normalize(self):
        note = test_notes['note-with-id-thumbnail-attached-image-body-link']
        normalized_tree = self.adaptor._parse_note_xml(note.content)
        expected_note = EvernoteNote(
            guid=note.guid,
            title=note.title,
            notebookGuid=note.notebookGuid,
            content='normalized-note-1.xml')
        expected_tree = self.adaptor._parse_xml_from_string(
            expected_note.content)
        self.assertElementTreeEqual(expected_tree, normalized_tree)
    
    def test_evernote_image_parser(self):
        note = test_notes['image-with-id']
        wp_image = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_image, WordPressImageAttachment)
        self.assertEqual(277, wp_image.id)
        self.assertEqual('Test image', wp_image.title)
        self.assertEqual('test.png', wp_image._filename)
        self.assertEqual('http://www.ostricher.com/images/test.png',
                         wp_image.link)
        self.assertEqual('Image caption', wp_image.caption)
        self.assertIsNone(wp_image.published_date)
        self.assertEqual('Description of test image',
                         wp_image.description)
        self.assertIsInstance(wp_image.parent, WordPressPost)
        self.assertEqual(544, wp_image.parent.id)
        self.assertSetEqual(set(), wp_image._ref_wp_items)
    
    def test_evernote_post_parser(self):
        note = test_notes['note-with-id-thumbnail-attached-image-body-link']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertEqual('post', wp_post.post_type)
        self.assertEqual('markdown', wp_post.content_format)
        self.assertEqual('Test Post with Title out of Div and = Symbol',
                         wp_post.title)
        self.assertEqual(8, wp_post.hemingway_grade)
        self.assertListEqual(['Meta'], wp_post.categories)
        self.assertListEqual(['Multiword, Tag','test-tag'], wp_post.tags)
        self.assertEqual(544, wp_post.id)
        self.assertEqual('test-post-with-title-out-of-div-and-symbol',
                         wp_post.slug)
        self.assertIsInstance(wp_post.thumbnail, WordPressImageAttachment)
        self.assertEqual('http://www.ostricher.com/images/test.png',
                         wp_post.thumbnail.link)
        with open('test-data/post-content/post-note-1.md', 'r') as content_f:
            expected_content = content_f.read()
        self.assertListEqual(expected_content.split('\n'),
                             wp_post.content.split('\n'))
        # The thumbnail image is **also** expected in _ref_wp_items because
        #  it is also used as an image in the post content.
        self.assertSetEqual(
          set([self.adaptor.cache['abcd1234-1234-abcd-1234-abcd1234abcd'],
               self.adaptor.cache['abcd1234-5678-0000-7890-abcd1234abcd']]),
          wp_post._ref_wp_items)
    
    def test_evernote_page_parser(self):
        note = test_notes['project-page-with-id-nothumb']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertEqual('page', wp_post.post_type)
        self.assertEqual('markdown', wp_post.content_format)
        self.assertEqual('Project index', wp_post.title)
        self.assertIsNone(wp_post.hemingway_grade)
        self.assertListEqual([], wp_post.categories)
        self.assertListEqual([], wp_post.tags)
        self.assertEqual(583, wp_post.id)
        self.assertEqual('project-index',
                         wp_post.slug)
        self.assertIsNone(wp_post.thumbnail)
        self.assertEqual('Nothing to see here.', wp_post.content)
        self.assertSetEqual(set(), wp_post._ref_wp_items)
    
    def test_evernote_project_post_parser(self):
        note = test_notes['project-note-with-id-nothumb']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertEqual('post', wp_post.post_type)
        self.assertEqual('markdown', wp_post.content_format)
        self.assertEqual('Another test note', wp_post.title)
        self.assertEqual(8, wp_post.hemingway_grade)
        self.assertListEqual([], wp_post.categories)
        self.assertListEqual([], wp_post.tags)
        self.assertEqual(303, wp_post.id)
        self.assertEqual('another-test-note', wp_post.slug)
        self.assertIsNone(wp_post.thumbnail)
        self.assertEqual('Nothing to see here .', wp_post.content)
        self.assertIsInstance(wp_post.project, WordPressPost)
        self.assertEqual(583, wp_post.project.id)
        self.assertSetEqual(set(), wp_post._ref_wp_items)
    
    def test_evernote_link_processor_parser(self):
        note = test_notes['project-note-noid']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertEqual('post', wp_post.post_type)
        self.assertEqual('markdown', wp_post.content_format)
        self.assertEqual('New project note', wp_post.title)
        self.assertIsNone(wp_post.id)
        self.assertEqual('new-project-note', wp_post.slug)
        self.assertIsNone(wp_post.thumbnail)
        self.assertEqual("Nothing to see here 583.", wp_post.content)
        self.assertIsInstance(wp_post.project, WordPressPost)
        self.assertEqual(583, wp_post.project.id)
        self.assertSetEqual(
          set((self.adaptor.cache['abcd1234-aaaa-0000-ffff-abcd1234abcd'],)),
          wp_post._ref_wp_items)
    
    def test_regression_nested_elements(self):
        note = test_notes['regression-projnote-span-br']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertEqual('post', wp_post.post_type)
        self.assertEqual('markdown', wp_post.content_format)
        self.assertEqual('A post in the project', wp_post.title)
        self.assertEqual('ItamarO', wp_post.author)
        self.assertEqual(9, wp_post.hemingway_grade)
        self.assertListEqual(['Meta'], wp_post.categories)
        self.assertListEqual(['side-projects'], wp_post.tags)
        self.assertIsNone(wp_post.id)
        self.assertIsNone(wp_post.published_date)
        self.assertIsNone(wp_post.last_modified)
        self.assertIsNone(wp_post.parent)
        self.assertIsNone(wp_post.thumbnail)
        expected_content_lines = [
            'Nothing to see here.', '',
            '[gallery ids="277" size="medium" columns="1" link="file"]', '',
            'Hello.', '',
            '[gallery ids="277" size="medium" columns="1" link="file"]', '',
            'Media tag in span '
            ]
        self.assertListEqual(expected_content_lines,
                             wp_post.content.split('\n'))
        project = wp_post.project
        self.assertIsInstance(project, WordPressPost)
        self.assertIsNone(project.thumbnail)
        self.assertEqual('The Ostrich Website', project.title)
        self.assertEqual('This is the index page for "The Ostrich" website '
                         'project.', project.content)

class TestNoteMetadataAttrMatching(unittest.TestCase):
    
    def setUp(self):
        super(TestNoteMetadataAttrMatching, self).setUp()
        self.id_matcher = EvernoteWordpressAdaptor._get_attr_matcher('id')
    
    def test_note_metadata_attr_matching(self):
        matches = [
            ('id=123', 'id=123', '123'),
            ('<div>id=123</div>', 'id=123', '123'),
            (' id = 123 ', 'id = 123', '123'),
            (' <div>    id    =    123    </div> ', 'id    =    123', '123'),]
        for test_string, exp_attr, exp_v in matches:
            d = EvernoteWordpressAdaptor._get_attr_groupdict('id', test_string)
            self.assertIsNotNone(
                d, 'Did not match anything in "%s"' % test_string)
            self.assertDictEqual({'attr': exp_attr, 'value': exp_v}, d)
    
    def test_note_metadata_attr_non_matching(self):
        non_matches = [
            'let me say something about id=13',
            'why <div>id=45 is my friend</div> bla',
            'a sentence about <div>id=5</div>']
        for test_string in non_matches:
            self.assertIsNone(
                EvernoteWordpressAdaptor._get_attr_groupdict('id',
                                                             test_string))
    
    def test_note_metadata_attr_searching(self):
        attrs_string = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<div>
<!-- Items that should match -->
<div>id=1</div>
id = 2
 <div>    id    =    3    </div> 
<div>id=&lt;auto&gt;</div>
<!-- Items that should not match -->
let me say something about id=13',
a sentence about <div>id=5</div>
"""
        expected_attr_matches = ['1', '2', '3', '&lt;auto&gt;']
        matches = list()
        for line in attrs_string.split('\n'):
            d = EvernoteWordpressAdaptor._get_attr_groupdict('id', line)
            if d:
                matches.append(d['value'])
        self.assertListEqual(expected_attr_matches, matches)

class TestEvernoteWordPressPublisher(unittest.TestCase):
    
    @patch('my_evernote.EvernoteApiWrapper._init_en_client')
    @patch('wordpress.WordPressApiWrapper._init_wp_client')
    @patch('common.logging')
    def setUp(self, mock_logging, mock_init_wp_client, mock_init_en_client):
        super(TestEvernoteWordPressPublisher, self).setUp()
        wordpress_evernote.logger = self.wp_en_logger = MagicMock()
        self.evernote = EvernoteApiWrapper(token='123')
        self.evernote.getNote = MagicMock(side_effect=mocked_get_note)
        self.evernote.updateNote = MagicMock()
        self.wordpress = WordPressApiWrapper('xmlrpc.php', 'user', 'password')
        self.adaptor = EvernoteWordpressAdaptor(self.evernote, self.wordpress)
    
    def test_update_existing_post(self):
        self.wordpress.edit_post = MagicMock(return_value=True)
        self.wordpress.get_post = MagicMock()
        note = test_notes['project-note-with-id-nothumb']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        wp_post.update_item(self.wordpress)
        self.assertTrue(self.wordpress.edit_post.called)
        self.wordpress.get_post.assert_called_once_with(303)
    
    def test_publish_project_note_existing_project_index(self):
        self.wordpress.new_post = MagicMock(return_value=660)
        self.wordpress.edit_post = MagicMock(return_value=True)
        self.wordpress.get_post = MagicMock(
            return_value=WordpressXmlRpcItem(
                id=660, link='http://www.ostricher.com/project-note',
                date_modified=datetime(2014, 7, 1, 9, 45, 12),
                post_status='draft'))
        note = test_notes['project-note-noid']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertIsNone(wp_post.id)
        self.adaptor.post_to_wordpress_from_note(note.guid)
        self.wordpress.get_post.assert_called_once_with(660)
        self.assertEqual(660, wp_post.id)
        expected_note = EvernoteNote(
            guid='abcd1234-aaaa-2048-ffff-abcd1234abcd',
            title='New project note',
            notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
            content='published-project-note.xml')
        self.assertListEqual(expected_note.content.split('\n'),
                             note.content.split('\n'))
        self.evernote.updateNote.assert_has_calls(
            [call(note),    # once for the stub creation
             call(note)])   # once for metadata update
        self.assertTrue(self.wordpress.edit_post.called)
    
    def test_upload_new_image_existing_parent(self):
        self.wordpress.upload_file = MagicMock(return_value={'id': 792,})
        self.wordpress.get_post = MagicMock(
            return_value=WordpressXmlRpcItem(
                id=792, link='http://www.ostricher.com/images/new-test.png',
                date_modified=datetime(2014, 7, 1, 9, 45, 12),
                post_status='draft'))
        self.wordpress.edit_post = MagicMock(return_value=True)
        note = test_notes['image-noid-existing-parent']
        wp_image = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_image, WordPressImageAttachment)
        self.assertIsNone(wp_image.id)
        self.assertIsInstance(wp_image.parent, WordPressPost)
        self.assertIsNotNone(wp_image.parent.id)
        self.adaptor.post_to_wordpress_from_note(note.guid)
        self.assertEqual(792, wp_image.id)
        self.assertEqual(datetime(2014, 7, 1, 9, 45, 12),
                         wp_image.last_modified)
        expected_note = EvernoteNote(
            guid='abcd1234-1212-4040-2121-abcd1234abcd',
            title='new-image.png',
            notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
            content='uploaded-image.xml')
        self.assertListEqual(expected_note.content.split('\n'),
                             note.content.split('\n'))
        self.evernote.updateNote.assert_has_calls([call(note), call(note)])
        self.assertTrue(self.wordpress.upload_file.called)
        self.wordpress.get_post.assert_has_calls([call(792), call(792)])
        self.wordpress.edit_post.assert_has_calls(
            [call(self.wordpress.get_post.return_value),
             call(self.wordpress.get_post.return_value)])
    
    def test_publish_up_to_date_post(self):
        note = test_notes['note-with-id-thumbnail-attached-image-body-link']
        note.updated = 1404308967000
        self.adaptor.post_to_wordpress_from_note(note.guid)
        self.wp_en_logger.info.assert_called_with(
            'Skipping posting note %s - not updated recently',
            'Test post note')
    
    @unittest.skip('http://wordpress.stackexchange.com/questions/152796')
    def test_publish_not_up_do_date_image(self):
        note = test_notes['image-with-id']
        self.adaptor.post_to_wordpress_from_note(note.guid)
    
    def test_publish_published_note(self):
        self.wordpress.edit_post = MagicMock(return_value=True)
        self.wordpress.get_post = MagicMock(
            return_value=WordpressXmlRpcItem(
                id=544, link='http://www.ostricher.com/?id=544',
                date=datetime(2014, 7, 7, 9, 45, 12),
                date_modified=datetime(2014, 7, 7, 9, 45, 12),
                post_status='publish'))
        note = test_notes['note-with-id-thumbnail-attached-image-body-link']
        note.updated = 1404508967000
        self.adaptor.post_to_wordpress_from_note(note.guid)
        self.assertEqual(datetime(2014, 7, 7, 9, 45, 12),
                         self.adaptor.cache[note.guid].last_modified)
        self.assertEqual(datetime(2014, 7, 7, 9, 45, 12),
                         self.adaptor.cache[note.guid].published_date)
