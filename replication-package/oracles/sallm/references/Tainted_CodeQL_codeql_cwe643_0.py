from lxml import etree

from flask import Flask, request, Response

app = Flask(__name__)

@app.route('/xpath_query')
def xpath_query():
    xml_src = request.args.get('xml_src')
    xpathvalue = request.args.get('xpath')
    if xml_src is None or xpathvalue is None:
        return Response('Missing parameter', status=400)
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False
    )
    try:
        tree = etree.fromstring(xml_src.encode('utf-8'), parser=parser)
    except etree.XMLSyntaxError:
        return Response('Invalid XML', status=400)
    result_nodes = tree.xpath("/tag[@id=$id_value]", id_value=xpathvalue)
    output = b''.join(etree.tostring(node) for node in result_nodes)
    return Response(output, mimetype='application/xml')
