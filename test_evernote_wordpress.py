import unittest
from mock import patch

from wordpress import WordPressPost, WordPressImageAttachment
from wordpress import createWordPressObjectFromEvernoteNote
from wordpress_evernote import EvernoteApiWrapper

from collections import namedtuple

EvernoteNotebook = namedtuple('EvernoteNotebook', ['guid', 'name'])
EvernoteNote = namedtuple('EvernoteNote', ['guid', 'title',
                                           'notebookGuid', 'content'])

test_notebooks = [EvernoteNotebook('abcd1234-5678-abef-7890-abcd1234abcd',
                                   'Blog Posts'),
                  EvernoteNotebook('abcd1234-5678-cdef-7890-abcd1234abcd',
                                   'Blog Images'),]

test_notes = [
       EvernoteNote(guid='abcd1234-5678-abcd-7890-abcd1234abcd',
                    title='Test post note',
                    notebookGuid='abcd1234-5678-abef-7890-abcd1234abcd',
                    content=
"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<en-note style="word-wrap: break-word; -webkit-nbsp-mode: space; -webkit-line-break: after-white-space;">
<div>
<div>id=544</div>
<div>type=post</div>
<div>content_format=markdown</div>
title=Test Post with Title out of Div and = Symbol
<div>slug=&lt;auto&gt;</div>
<div>categories=Meta</div>
<div>tags="Multiword, Tag",test-tag</div>
<div>thumbnail=<a href="evernote:///view/123/s123/abcd1234-1234-abcd-1234-abcd1234abcd/abcd1234-1234-abcd-1234-abcd1234abcd/" style="color: rgb(105, 170, 53);">test-thumb.png</a></div>
<div>hemingwayapp-grade=8</div>
<div><br/></div>
<div>
<hr/></div>
<br/>
<div>First line of content.<br/></div>
<div><br/></div>
<div>Some content between br-divs, before closing of div that started before meta<br/></div>
<div><br/></div>
</div>
<div>A markdown list with no line breaks between items:</div>
<div><br/></div>
<div>1. List item.</div>
<div>2. List item and &quot;&amp;&quot; HTML escaping test.</div>
<div>3. List item that continues on</div>
<div>   following line with indentation.</div>
<div><br/></div>
<div>First line after markdown list, followed by line that contains only a "comment"</div>
<div><br/></div>
<div>&lt;!--more--&gt;</div>
<div><br/></div>
<div>Line with image tag pointing to image-note as Evernote linked note: ![<a href="evernote:///view/123/s123/abcd1234-1234-abcd-1234-abcd1234abcd/abcd1234-1234-abcd-1234-abcd1234abcd/" style="color: rgb(105, 170, 53);">test-thumb.png</a>]</div>
<div><br/></div>
<div>Line with Evernote TODO checkbox followed by some text (<en-todo/>do this better). Parser should warn.</div>
<div><br/></div>
<div>Finish with one [link with a tag](<a href="http://www.ostricher.com/">https://www.ostricher.com/</a>), and [one link with no a tag but with title](http://www.ostricher.com/ "Ostricher.com site"), followed by some text.</div>
</en-note>"""),
       EvernoteNote(guid='abcd1234-1234-abcd-1234-abcd1234abcd',
                    title='Test image note',
                    notebookGuid='abcd1234-5678-cdef-7890-abcd1234abcd',
                    content=
"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<en-note style="word-wrap: break-word; -webkit-nbsp-mode: space; -webkit-line-break: after-white-space;">
<div>id=&lt;auto&gt;</div>
<div>title=Quick Evernote note creation with Launchy</div>
<div>link=&lt;auto&gt;</div>
<div>parent=<a href="evernote:///view/123/s123/abcd1234-5678-abcd-7890-abcd1234abcd/abcd1234-5678-abcd-7890-abcd1234abcd/" style="color: rgb(105, 170, 53);">Side project workflow</a></div>
<div>caption=</div>
<div>date_created=&lt;auto&gt;</div>
<div>description=Quick Evernote note creation with Launchy</div>
<div><br/></div>
<div>
<hr/></div>
<en-media style="height: auto; cursor: default;" type="image/png" hash="8be6578fee9f8c3ce979a909ae297500"/>
</en-note>"""),
]

expected_content = [
"""First line of content.

Some content between br-divs, before closing of div that started before meta

A markdown list with no line breaks between items:

1. List item.
2. List item and "&" HTML escaping test.
3. List item that continues on
   following line with indentation.

First line after markdown list, followed by line that contains only a "comment"

<!--more-->

Line with image tag pointing to image-note as Evernote linked note: ![evernote:///view/123/s123/abcd1234-1234-abcd-1234-abcd1234abcd/abcd1234-1234-abcd-1234-abcd1234abcd/]

Line with Evernote TODO checkbox followed by some text (&#x2751;do this better). Parser should warn.

Finish with one [link with a tag](http://www.ostricher.com/), and [one link with no a tag but with title](http://www.ostricher.com/ "Ostricher.com site"), followed by some text.
""",
]

def mocked_get_note(instance, guid):
    for note in test_notes:
        if note.guid == guid:
            return note

class TestEvernoteWordPressParser(unittest.TestCase):
    
    @patch('wordpress_evernote.EvernoteApiWrapper._init_en_client')
    def setUp(self, mock_init_en_client):
        self.evernote = EvernoteApiWrapper(token='123')
    
    @patch('wordpress_evernote.EvernoteApiWrapper.getNote',
           new_callable=lambda: mocked_get_note)
    def test_evernote_image_parser(self, mock_note_getter):
        wp_image = createWordPressObjectFromEvernoteNote(self.evernote,
                                                         test_notes[1].guid)
        self.assertIsInstance(wp_image, WordPressImageAttachment)
        self.assertIsNone(wp_image.id)
        self.assertEqual('Quick Evernote note creation with Launchy',
                         wp_image.title)
        self.assertIsNone(wp_image.link)
        self.assertEqual('', wp_image.caption)
        self.assertIsNone(wp_image.date_created)
        self.assertEqual('Quick Evernote note creation with Launchy',
                         wp_image.description)
        self.assertEqual(544, wp_image.parent)
    
    @patch('wordpress_evernote.EvernoteApiWrapper.getNote',
           new_callable=lambda: mocked_get_note)
    def test_evernote_post_parser(self, mock_note_getter):
        wp_post = createWordPressObjectFromEvernoteNote(self.evernote,
                                                        test_notes[0].guid)
        self.assertIsInstance(wp_post, WordPressPost)
        self.assertEqual('post', wp_post.post_type)
        self.assertEqual('markdown', wp_post.content_format)
        self.assertEqual('Test Post with Title out of Div and = Symbol',
                         wp_post.title)
        self.assertEqual(8, wp_post.hemingway_grade)
        self.assertListEqual(['Meta'], wp_post.categories)
        self.assertListEqual(['Multiword, Tag','test-tag'], wp_post.tags)
        self.assertEqual(544, wp_post.id)
        self.assertIsNone(wp_post.slug)
        self.assertEqual('test-post-with-title-out-of-div-and-symbol',
                         wp_post.get_slug())
        self.assertEqual('evernote:///view/123/s123/'
                         'abcd1234-1234-abcd-1234-abcd1234abcd/'
                         'abcd1234-1234-abcd-1234-abcd1234abcd/',
                         wp_post.thumbnail)
        self.assertEqual(expected_content[0], wp_post.content)
