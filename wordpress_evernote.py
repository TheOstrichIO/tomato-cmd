#!/usr/bin/python
# -*- coding: utf-8 -*-

import settings
import common
from wordpress import WordPressApiWrapper, WordPressPost
from wordpress import WordPressItem, WordPressImageAttachment
from my_evernote import EvernoteApiWrapper

logger = common.logger.getChild('wordpress-evernote')

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
