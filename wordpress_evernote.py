#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
import re
import argparse

import settings
import common
from wordpress import WordPressApiWrapper, WordPressPost
from wordpress import WordPressItem, WordPressImageAttachment
from my_evernote import EvernoteApiWrapper

wp_en_parser = argparse.ArgumentParser(
    description='WordPress <--> Evernote utilities')
wp_en_parser.add_argument('--wordpress',
                          default='default',
                          help='WordPress account name to use from settings.')
subparsers = wp_en_parser.add_subparsers()

logger = common.logger.getChild('wordpress-evernote')

###############################################################################

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
    
    def __init__(self, en_wrapper, wp_wrapper):
        """Initialize Adaptor instance with API wrapper objects.
        
        Args:
            @param en_wrapper: Initialized Evernote API wrapper instance.
            @type en_wrapper: my_evernote.EvernoteApiWrapper
            @param wp_wrapper: Initialized Wordpress API wrapper instance.
            @type wp_wrapper: wordpress.WordPressApiWrapper
        """
        self.evernote = en_wrapper
        self.wordpress = wp_wrapper
    
    def update_note_metadata_from_wordpress_post(self, note, post):
        """Updates an Evernote post note metadata based on Wordpress post item.
        
        Updates only fields that has WordPress as the authoritative source,
        like ID & link.
        
        @requires: `post` was originally constructed from `note`.
        
        Args:
          @param note: Evernote post-note to update
          @type note: evernote.edam.type.ttypes.Note
          @param post: Wordpress post from which to update
          @type post: wordpress.WordPressPost
        
        Exceptions:
          @raise RuntimeError: If ID is set and differs
        """
        # TODO: get authoritative attributes from WordPress class
        attrs_to_update = (('id', str(post.id)), ) #('link', post.link),)
        modified_flag = False
        content_lines = note.content.split('\n')
        for linenum, line in enumerate(content_lines):
            if self._hr_matcher.search(line):
                # <hr /> tag means end of metadata section
                break
            for attr, post_val in attrs_to_update:
                m = self._get_attr_matcher(attr).match(line)
                if m:
                    current_val = m.groupdict()['value']
                    if post_val == current_val:
                        logger.debug('No change in attribute "%s"', attr)
                    else:
                        logger.debug('Changing note attribute "%s" from "%s" '
                                     'to "%s"', attr, current_val, post_val)
                        attr_str = m.groupdict()['attr']
                        content_lines[linenum] = line.replace(
                            attr_str, '%s=%s' % (attr, post_val))
                        modified_flag = True
        if modified_flag:
            logger.info('Writing modified content back to note')
            note.content = '\n'.join(content_lines)
            self.evernote.updateNote(note)
        else:
            logger.info('No changes to note content')

def save_wp_image_to_evernote(en_wrapper, notebook_name, wp_image,
                              force=False):
    # lookup existing WordPress image note
    note_title = u'%s <%s>' % (wp_image.filename, wp_image.id)
    image_note = en_wrapper.getSingleNoteByTitle(note_title, notebook_name)
    if not image_note or force:
        # prepare resource and note
        resource, resource_tag = en_wrapper.makeResource(wp_image.image(),
                                                         wp_image.filename)
        note_content = '%s\r\n<hr/>\r\n' % (resource_tag)
        for attr in WordPressImageAttachment._slots:
            note_content += '<div>%s=%s</div>\r\n' % (attr,
                                                      getattr(wp_image, attr))
        wp_image_note = en_wrapper.makeNote(title=note_title,
                                            content=note_content,
                                            resources=[resource])
    if image_note:
        # note exists
        logger.info('WP Image note "%s" exists in Evernote', note_title)
        if force:
            logger.info('Updating note with WordPress version.')
            # update existing note with overwritten content
            wp_image_note.guid = image_note.guid
            en_wrapper.updateNote(wp_image_note)
        else:
            logger.debug('Skipping note update')
    else:
        # create new note
        logger.info('Creating new WP Image note "%s"', note_title)
        en_wrapper.saveNoteToNotebook(wp_image_note, notebook_name)

def publish_post_draft_from_evernote(en_wrapper, wp_wrapper, en_note_link):
    """Create WordPress post from Evernote note,
    and publish it to a WordPress blog.
    
    @param `en_wrapper`: Initialized EvernoteApiWrapper object for getting note
    @type en_wrapper: EvernoteApiWrapper
    @param `wp_wrapper`: Initialized WordPressApiWrapper object
    @type wp_wrapper: WordPressApiWrapper
    @param `en_note_link`: Evernote note link string ("evernote://...") for
                            note with post to publish.
    """
    #: :type wp_post: WordPressPost
    wp_post = WordPressItem.createFromEvernote(en_note_link, en_wrapper)
    assert(isinstance(wp_post, WordPressPost))
    wp_post.publishItem(wp_wrapper)

def _get_wrappers(args):
    wp_account = settings.WORDPRESS[args.wordpress]
    # Each entry can be either a WordPressCredentials object,
    # or a name of another entry.
    while not isinstance(wp_account, settings.WordPressCredentials):
        wp_account = settings.WORDPRESS[wp_account]
    logger.debug('Working with WordPress at URL "%s"', wp_account.xmlrpc_url)
    wp_wrapper = WordPressApiWrapper(wp_account.xmlrpc_url,
                                     wp_account.username, wp_account.password)
    en_wrapper = EvernoteApiWrapper(settings.enDevToken_PRODUCTION)
    return (wp_wrapper, en_wrapper)

###############################################################################

def post_note(args):
    """ArgParse handler for post-note command."""
    wp_wrapper, en_wrapper = _get_wrappers(args)
    publish_post_draft_from_evernote(en_wrapper, wp_wrapper, args.en_link)
    # TODO: update note with ID and stuff

post_parser = subparsers.add_parser('post-note',
                                    help='Create a WordPress post from '
                                         'Evernote note')
post_parser.add_argument('en_link',
                         help='Evernote note to post '
                              '(full link, or just GUID)')
post_parser.set_defaults(func=post_note)

###############################################################################

def _images_to_evernote():
    wp_wrapper = WordPressApiWrapper(settings.wpXmlRpcUrl,
                                     settings.wpUsername, settings.wpPassword)
    en_wrapper = EvernoteApiWrapper(settings.enDevToken_PRODUCTION)
    for wp_image in wp_wrapper.mediaItemGenerator():
        save_wp_image_to_evernote(en_wrapper, '.zImages', wp_image)

def _custom_fields():
    wp_wrapper = WordPressApiWrapper(settings.wpXmlRpcUrl,
                                     settings.wpUsername, settings.wpPassword)
    for wp_post in wp_wrapper.postGenerator():
        print wp_post, wp_post.custom_fields

def main():
    # _custom_fields()
    args = wp_en_parser.parse_args()
    args.func(args)

if '__main__' == __name__:
    main()
