import unittest
from mock import patch, Mock, MagicMock
import os

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
            
    def _get_content(self, fname):
        fpath = os.path.join('test-data', 'notes-content', fname)
        with open(fpath, 'r') as note_file:
            return note_file.read()

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
        guid='abcd1234-1212-4040-2121--abcd1234abcd',
        title='new-image.png <auto>',
        notebookGuid='abcd1234-5678-cdef-7890-abcd1234abcd',
        content='image-no-id.xml',
        resources=[MagicMock()]),
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
        self.assertIsNone(wp_image.date_created)
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
            m = self.id_matcher.match(test_string)
            self.assertIsNotNone(
                m, 'Did not match anything in "%s"' % test_string)
            self.assertDictEqual({'attr': exp_attr, 'value': exp_v},
                                 m.groupdict())
    
    def test_note_metadata_attr_non_matching(self):
        non_matches = [
            'let me say something about id=13',
            '<div>id=45 is my friend</div>',
            'a sentence about <div>id=5</div>']
        for test_string in non_matches:
            self.assertIsNone(self.id_matcher.match(test_string))
    
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
<div>id=45 is my friend</div>
a sentence about <div>id=5</div>
"""
        expected_attr_matches = ['1', '2', '3', '&lt;auto&gt;']
        matches = list()
        for line in attrs_string.split('\n'):
            m = self.id_matcher.match(line)
            if m:
                matches.append(m.groupdict()['value'])
        self.assertListEqual(expected_attr_matches, matches)

class TestEvernoteWordPressPublisher(unittest.TestCase):
    
    @patch('my_evernote.EvernoteApiWrapper._init_en_client')
    @patch('wordpress.WordPressApiWrapper._init_wp_client')
    @patch('common.logging')
    def setUp(self, mock_logging, mock_init_wp_client, mock_init_en_client):
        super(TestEvernoteWordPressPublisher, self).setUp()
        wordpress_evernote.logger = MagicMock()
        self.evernote = EvernoteApiWrapper(token='123')
        self.evernote.getNote = MagicMock(side_effect=mocked_get_note)
        self.evernote.updateNote = MagicMock()
        self.wordpress = WordPressApiWrapper('xmlrpc.php', 'user', 'password')
        self.adaptor = EvernoteWordpressAdaptor(self.evernote, self.wordpress)
    
    def test_update_existing_post(self):
        self.wordpress.edit_post = MagicMock(return_value=True)
        note = test_notes['project-note-with-id-nothumb']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        wp_post.update_item(self.wordpress)
        self.assertTrue(self.wordpress.edit_post.called)
    
    def test_publish_project_note_existing_project_index(self):
        self.wordpress.new_post = MagicMock(return_value=660)
        self.wordpress.edit_post = MagicMock(return_value=True)
        note = test_notes['project-note-noid']
        wp_post = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertIsNone(wp_post.id)
        self.adaptor.post_to_wordpress_from_note(note.guid)
        self.assertEqual(660, wp_post.id)
        expected_note = EvernoteNote(
            guid='abcd1234-aaaa-2048-ffff-abcd1234abcd',
            title='New project note',
            notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
            content='published-project-note.xml')
        self.assertListEqual(expected_note.content.split('\n'),
                             note.content.split('\n'))
        self.evernote.updateNote.assert_called_once_with(note)
        self.assertTrue(self.wordpress.edit_post.called)
    
    def test_upload_new_image_existing_parent(self):
        self.wordpress.upload_file = MagicMock(return_value={'id': 792,})
        self.wordpress.get_post = MagicMock()
        self.wordpress.edit_post = MagicMock(return_value=True)
        note = test_notes['image-noid-existing-parent']
        wp_image = self.adaptor.wp_item_from_note(note.guid)
        self.assertIsInstance(wp_image, WordPressImageAttachment)
        self.assertIsNone(wp_image.id)
        self.assertIsInstance(wp_image.parent, WordPressPost)
        self.assertIsNotNone(wp_image.parent.id)
        self.adaptor.post_to_wordpress_from_note(note.guid)
        self.assertEqual(792, wp_image.id)
        expected_note = EvernoteNote(
            guid='abcd1234-1212-4040-2121--abcd1234abcd',
            title='new-image.png <auto>',
            notebookGuid='abcd1234-5678-1928-7890-abcd1234abcd',
            content='uploaded-image.xml')
        self.assertListEqual(expected_note.content.split('\n'),
                             note.content.split('\n'))
        self.evernote.updateNote.assert_called_once_with(note)
        self.assertTrue(self.wordpress.upload_file.called)
        self.wordpress.get_post.assert_called_once_with(792)
        self.assertTrue(self.wordpress.edit_post.called)
        self.wordpress.edit_post.assert_called_once_with(
            792, self.wordpress.get_post.return_value)
    
    def test_publish_new_note_with_new_thumbnail(self):
        pass
