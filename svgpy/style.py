# Copyright (C) 2018 Tetsuya Miura <miute.dev@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from logging import getLogger

from lxml import etree, cssselect

from .css import CSSParser, CSSRule, CSSStyleSheet
from .utils import normalize_url


_SVG_UA_CSS_STYLESHEET = '''
@namespace url(http://www.w3.org/2000/svg);
@namespace xml url(http://www.w3.org/XML/1998/namespace);

svg:not(:root), hatch, image, marker, pattern, symbol { overflow: hidden; }

*:not(svg),
*:not(foreignObject) > svg {
  transform-origin: 0 0;
}

*[xml|space=preserve] {
  text-space-collapse: preserve-spaces;
}

defs,
clipPath, mask, marker,
desc, title, metadata,
pattern, hatch,
linearGradient, radialGradient, meshGradient,
script, style,
symbol {
  display: none !important;
}
:host(use) > symbol {
  display: inline !important;
}
'''

# _OPENTYPE_UA_CSS_STYLESHEET = '''
# @namespace svg url(http://www.w3.org/2000/svg);
#
# svg|text, svg|foreignObject {
#   display: none !important;
# }
# '''

logger = getLogger(__name__)


def flatten_css_rules(element, css_rules):
    doc = element.owner_document
    win = doc.default_view if doc is not None else None
    flattened = list()
    for css_rule in css_rules:
        if css_rule.type == CSSRule.IMPORT_RULE:
            # '@import' at-rule
            media = css_rule.media.media_text
            if media not in ['', 'all']:
                if win is None:
                    logger.debug('no active window: {}'.format(element))
                    continue
                mql = win.match_media(media)
                if not mql.matches:
                    logger.debug('media not matched: {}'.format(repr(media)))
                    continue
            flattened.extend(
                flatten_css_rules(element, css_rule.style_sheet.css_rules))
        elif css_rule.type == CSSRule.MEDIA_RULE:
            # '@media' at-rule
            media = css_rule.media.media_text
            if media not in ['', 'all']:
                if win is None:
                    logger.debug('no active window: {}'.format(element))
                    continue
                mql = win.match_media(media)
                if not mql.matches:
                    logger.debug('media not matched: {}'.format(repr(media)))
                    continue
            flattened.extend(
                flatten_css_rules(element, css_rule.css_rules))
        else:
            flattened.append(css_rule)
    return flattened


def get_css_rules(element):
    css_rules = CSSParser.fromstring(_SVG_UA_CSS_STYLESHEET)

    root = element.getroottree().getroot()

    style_sheets = get_css_style_sheets_from_xml_stylesheet(root)
    for css_style_sheet in style_sheets:
        css_rules.extend(css_style_sheet.css_rules)

    style_sheets = get_css_style_sheets_from_svg_document(root)
    for css_style_sheet in style_sheets:
        css_rules.extend(css_style_sheet.css_rules)

    flattened = flatten_css_rules(element, css_rules)
    return flattened


def get_css_style_sheet_from_element(element, doc=None):
    local_name = element.local_name
    if local_name not in ['link', 'style']:
        raise ValueError(
            'Expected <link> or <style> element, got <{}>'.format(local_name))
    if doc is None:
        doc = element.owner_document
    if doc is not None:
        win = doc.default_view
        base_url = doc.document_uri
    else:
        win = None
        base_url = None

    if local_name == 'link':
        rel_list = element.rel_list
        if 'stylesheet' not in rel_list or 'alternate' in rel_list:
            logger.debug('not a style sheet: {}: relList: {}'.format(
                element, repr(rel_list)))
            return None  # TODO: support alternative style sheet.
        href = element.href
        if href is None or href[0] == '#':
            logger.debug('invalid URL: {}: href: {}'.format(
                element, repr(href)))
            return None
        media = element.media
        if media != 'all':
            if win is None:
                logger.debug('no active window: {}'.format(element))
                return None
            mql = win.match_media(media)
            if not mql.matches:
                logger.debug('media not matched: {}: {}'.format(
                    element, repr(media)))
                return None
        url = normalize_url(href, base_url)
        css_style_sheet = CSSParser.parse(url.href,
                                          owner_node=element)
        return css_style_sheet
    else:  # 'style'
        if element.type != 'text/css' or element.text is None:
            logger.debug(
                'not a style sheet: {}: type: {}: size = {}'.format(
                    element,
                    repr(element.type),
                    0 if element.text is None else len(element.text)))
            return None
        media = element.media
        if media != 'all':
            if win is None:
                logger.debug('no active window: {}'.format(element))
                return None
            mql = win.match_media(media)
            if not mql.matches:
                logger.debug('media not matched: {}: {}'.format(
                    element, repr(media)))
                return None
        css_style_sheet = CSSStyleSheet(type_=element.type,
                                        owner_node=element,
                                        title=element.title,
                                        media=element.media)
        css_rules = CSSParser.fromstring(element.text,
                                         parent_style_sheet=css_style_sheet)
        css_style_sheet.css_rules.extend(css_rules)
        return css_style_sheet


def get_css_style_sheets_from_svg_document(root):
    style_sheets = list()
    doc = root.owner_document
    for element in root.iter(tag=('{*}link', '{*}style')):
        # FIXME: iterated node's owner_document returns None.
        css_style_sheet = get_css_style_sheet_from_element(element, doc)
        if css_style_sheet is None:
            continue
        style_sheets.append(css_style_sheet)
    return style_sheets


def get_css_style_sheets_from_xml_stylesheet(root):
    style_sheets = list()
    doc = root.owner_document
    if doc is not None:
        win = doc.default_view
        base_url = doc.document_uri
    else:
        win = None
        base_url = None

    # 'lxml.etree.SiblingsIterator' object is not reversible
    siblings = root.itersiblings(preceding=True)
    elements = [it for it in siblings]
    elements.reverse()
    for element in elements:
        tag = etree.tostring(element).decode()
        if tag.split()[0] != '<?xml-stylesheet':
            continue
        href = element.get('href')
        if (href is None
                or href[0] == '#'
                or element.get('alternate', '') == 'yes'):
            logger.debug('not a style sheet: {}'.format(element))
            continue  # TODO: support alternative style sheet.
        media = element.get('media', 'all')
        if media != 'all':
            if win is None:
                logger.debug('no active window: {}'.format(root))
                continue
            mql = win.match_media(media)
            if not mql.matches:
                logger.debug('media not matched: {}'.format(repr(media)))
                continue
        encoding = element.get('charset')
        url = normalize_url(href, base_url)
        css_style_sheet = CSSParser.parse(url.href,
                                          owner_node=element,
                                          encoding=encoding)
        style_sheets.append(css_style_sheet)
    return style_sheets


def get_css_style(element, css_rules):
    style = dict()
    style_important = dict()
    namespaces = None
    for css_rule in css_rules:
        if css_rule.type == CSSRule.STYLE_RULE:
            try:
                selector = cssselect.CSSSelector(css_rule.selector_text,
                                                 namespaces=namespaces)
                matched = selector(element)
                if len(matched) > 0 and element in matched:
                    for key, (value, priority) in css_rule.style.items():
                        style[key] = value
                        if priority == 'important':
                            style_important[key] = value
            except cssselect.ExpressionError:
                pass
        elif css_rule.type == CSSRule.FONT_FACE_RULE:
            # TODO: support CSS @font-face at-rule.
            pass
        elif css_rule.type == CSSRule.FONT_FEATURE_VALUES_RULE:
            # TODO: support CSS @font-feature-values at-rule.
            pass
        elif css_rule.type == CSSRule.NAMESPACE_RULE:
            if len(css_rule.prefix) > 0:
                if namespaces is None:
                    namespaces = dict()
                namespaces[css_rule.prefix] = css_rule.namespace_uri
    return style, style_important
