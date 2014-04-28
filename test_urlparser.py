import unittest

from wordpress_evernote import UrlParser

class TestUrlParser(unittest.TestCase):
    
    def test_simple_url(self):
        urlp = UrlParser('http://www.example.com/')
        self.assertEqual('www.example.com', urlp.host)
        self.assertEqual('http', urlp.schema)
        self.assertEqual('', urlp.path)
        self.assertListEqual([''], urlp.path_parts())
        self.assertListEqual([], urlp.query)
        self.assertIsNone(urlp.tag)
        self.assertIsNone(urlp.port)
    
    def test_simple_url_with_path(self):
        urlp = UrlParser('http://www.example.com/path/to/some/file.html')
        self.assertEqual('www.example.com', urlp.host)
        self.assertEqual('http', urlp.schema)
        self.assertListEqual(['path', 'to', 'some', 'file.html'],
                             urlp.path_parts())
        self.assertListEqual([], urlp.query)
        self.assertIsNone(urlp.tag)
        self.assertIsNone(urlp.port)
    
    def test_the_bomb_with_qs(self):
        urlp = UrlParser('https://user:pass@www.example.com:123/some/file.html'
                         '?p1=v1&p2=v2')
        self.assertEqual('www.example.com', urlp.host)
        self.assertEqual('https', urlp.schema)
        self.assertListEqual(['some', 'file.html'],
                             urlp.path_parts())
        self.assertListEqual(['p1=v1', 'p2=v2'], urlp.query)
        self.assertIsNone(urlp.tag)
        self.assertEqual('123', urlp.port)
        self.assertEqual('user', urlp.user)
        self.assertEqual('pass', urlp.password)
    
    def test_the_bomb_with_tag(self):
        urlp = UrlParser('https://user@www.example.com:123/some/file.html'
                         '#sometag')
        self.assertEqual('www.example.com', urlp.host)
        self.assertEqual('https', urlp.schema)
        self.assertListEqual(['some', 'file.html'],
                             urlp.path_parts())
        self.assertListEqual([], urlp.query)
        self.assertEqual('sometag', urlp.tag)
        self.assertEqual('123', urlp.port)
        self.assertEqual('user', urlp.user)
        self.assertIsNone(urlp.password)
        
        
