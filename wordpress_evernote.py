#!/usr/bin/python
# -*- coding: utf-8 -*-

import settings
import common
from wordpress import WordPressApiWrapper, WordPressPost
from wordpress import WordPressItem, WordPressImageAttachment
from my_evernote import EvernoteApiWrapper

logger = common.logger.getChild('wordpress-evernote')

class EvernoteWordpressAdaptor(object):
    """Evernote-Wordpress Adaptor class.
    
    Attributes:
        @type self.evernote: my_evernote.EvernoteApiWrapper
    """
    
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
        # Find ID and set it if needed
        import re
        # RegEx for finding metadata attributes
        # - <attr-name> in beginning of line or immediately following ">"
        # - "=" after <attr-name>, optionally with whitespaces around it
        # - <value> after the "=" up to end of line or "<"
        re.match('[\A\>](?P<attr_name>\w+\s*\=\s*(?P<value>\w+)[\Z\<]',
                 note.content, re.IGNORECASE)
        note.content = ''
        pass

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

def main():
    wp_wrapper = WordPressApiWrapper(settings.wpXmlRpcUrl,
                                     settings.wpUsername, settings.wpPassword)
    en_wrapper = EvernoteApiWrapper(settings.enDevToken_PRODUCTION)
    #for wp_image in wp_wrapper.mediaItemGenerator():
    #    save_wp_image_to_evernote(en_wrapper, '.zImages', wp_image)
    for wp_post in wp_wrapper.postGenerator():
        print wp_post, wp_post.custom_fields

if '__main__' == __name__:
    main()
