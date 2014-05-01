import unittest
from mock import patch

from wordpress_evernote import EvernoteApiWrapper

class TestEvernoteApiWrapper(unittest.TestCase):
    
    @patch('wordpress_evernote.EvernoteApiWrapper._init_en_client')
    def setUp(self, mock_init_en_client):
        self.evernote = EvernoteApiWrapper(token='123')
    
    def testEvernoteLinkParser(self):
        link = self.evernote.parseNoteLinkUrl('evernote:///view/123/s123/'
                                       'abcd1234-1234-abcd-1234-abcd1234abcd/'
                                       'abcd1234-1234-abcd-1234-abcd1234abcd/')
        self.assertEqual('123', link.user_id)
        self.assertEqual('s123', link.shard_id)
        self.assertEqual('abcd1234-1234-abcd-1234-abcd1234abcd', link.noteGuid)
