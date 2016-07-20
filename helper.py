
import logging
from mako.template import Template


def write_mako_template(handler, filename, **kwargs):
    code, response = render_mako_template(filename, request=handler.request,
                                          **kwargs)
    if code != 200:
        handler.error(code)
    handler.response.out.write(response)


def render_mako_template(_filename, **kwargs):
    t = Template(filename=_filename,
                 default_filters=['decode.utf8'])
    try:
        return 200, t.render_unicode(**kwargs)
    except Exception as e:
        logging.info("Exception while rendering html : %s", e)
    return 500, "Server Error"
