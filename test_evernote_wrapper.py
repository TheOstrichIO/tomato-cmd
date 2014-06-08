import unittest

from wordpress_evernote import EvernoteApiWrapper

class TestEvernoteApiWrapper(unittest.TestCase):
    
    def test_evernote_link(self):
        link = EvernoteApiWrapper.parseNoteLinkUrl('evernote:///view/123/s123/'
                                       'abcd1234-1234-abcd-1234-abcd1234abcd/'
                                       'abcd1234-1234-abcd-1234-abcd1234abcd/')
        self.assertEqual('123', link.user_id)
        self.assertEqual('s123', link.shard_id)
        self.assertEqual('abcd1234-1234-abcd-1234-abcd1234abcd', link.noteGuid)
    
    def test_evernote_url(self):
        en_url = ('https://www.evernote.com/shard/s123/nl/112233/'
                  'abcd1234-1234-abcd-1234-abcd1234abcd')
        link = EvernoteApiWrapper.parseNoteLinkUrl(en_url)
        self.assertEqual('112233', link.user_id)
        self.assertEqual('s123', link.shard_id)
        self.assertEqual('abcd1234-1234-abcd-1234-abcd1234abcd', link.noteGuid)
