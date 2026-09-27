package com.gameweare.api.create;

import java.io.StringReader;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Set;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.xml.sax.InputSource;

/** SVG validation and emergency local cover art shared by the cover agent and catalog. */
public final class CoverGenerator {
    private static final Set<String> ELEMENTS = Set.of("svg", "g", "rect", "circle", "ellipse", "path",
            "line", "polyline", "polygon", "text", "tspan");
    private static final Set<String> ATTRIBUTES = Set.of("xmlns", "width", "height", "viewBox", "x", "y",
            "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "stroke",
            "stroke-width", "opacity", "font-size", "font-family", "font-weight", "text-anchor");

    record Cover(byte[] bytes, long promptTokens, long completionTokens, boolean degraded, String failureReason) {}

    static byte[] safeSvg(String raw) throws Exception {
        String svg = raw.strip().replaceFirst("(?is)^```(?:svg|xml)?\\s*", "")
                .replaceFirst("(?s)\\s*```$", "").strip();
        if (svg.length() > 100_000 || !svg.startsWith("<svg"))
            throw new IllegalArgumentException("Cover SVG is invalid or too large");
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
        factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setXIncludeAware(false);
        factory.setExpandEntityReferences(false);
        var document = factory.newDocumentBuilder().parse(new InputSource(new StringReader(svg)));
        if (!"svg".equals(document.getDocumentElement().getTagName()))
            throw new IllegalArgumentException("Cover root must be svg");
        validateNode(document.getDocumentElement());
        document.getDocumentElement().setAttribute("width", "1200");
        document.getDocumentElement().setAttribute("height", "900");
        document.getDocumentElement().setAttribute("viewBox", "0 0 1200 900");
        var transformerFactory = TransformerFactory.newInstance();
        transformerFactory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        var transformer = transformerFactory.newTransformer();
        transformer.setOutputProperty(OutputKeys.OMIT_XML_DECLARATION, "yes");
        StringWriter out = new StringWriter();
        transformer.transform(new DOMSource(document), new StreamResult(out));
        return out.toString().getBytes(StandardCharsets.UTF_8);
    }

    private static void validateNode(Node node) {
        if (node.getNodeType() != Node.ELEMENT_NODE) {
            if (node.getNodeType() != Node.TEXT_NODE) throw new IllegalArgumentException("Unsupported SVG node");
            return;
        }
        Element element = (Element) node;
        if (!ELEMENTS.contains(element.getTagName())) throw new IllegalArgumentException("Unsupported SVG element");
        var attributes = element.getAttributes();
        for (int i = 0; i < attributes.getLength(); i++) {
            Node attribute = attributes.item(i);
            String value = attribute.getNodeValue();
            if (!ATTRIBUTES.contains(attribute.getNodeName()) || value.length() > 5000
                    || ("xmlns".equals(attribute.getNodeName())
                        ? !"http://www.w3.org/2000/svg".equals(value)
                        : value.matches("(?is).*?(url\\s*\\(|javascript:|data:|https?:|[<>]).*")))
                throw new IllegalArgumentException("Unsafe SVG attribute");
        }
        for (Node child = node.getFirstChild(); child != null; child = child.getNextSibling()) validateNode(child);
    }

    public static byte[] fallback(String title, String request) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(request.getBytes(StandardCharsets.UTF_8));
            String color = HexFormat.of().formatHex(digest, 0, 3);
            String accent = HexFormat.of().formatHex(digest, 3, 6);
            String safeTitle = escape(title.length() > 54 ? title.substring(0, 54) : title);
            String svg = "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='900' viewBox='0 0 1200 900'>"
                    + "<rect width='1200' height='900' fill='#101923'/>"
                    + "<circle cx='940' cy='300' r='360' fill='#" + color + "' opacity='.34'/>"
                    + "<circle cx='180' cy='790' r='300' fill='#" + accent + "' opacity='.3'/>"
                    + "<rect x='74' y='86' width='1052' height='728' rx='42' fill='#152633' opacity='.82'/>"
                    + "<circle cx='924' cy='410' r='154' fill='#" + accent + "' opacity='.8'/>"
                    + "<circle cx='924' cy='410' r='88' fill='#101923'/>"
                    + "<text x='126' y='230' fill='#c5f779' font-family='Arial' font-size='34' font-weight='700'>GAMEWEARE / PLAY</text>"
                    + "<text x='126' y='520' fill='#ffffff' font-family='Arial' font-size='62' font-weight='700'>"
                    + safeTitle + "</text>"
                    + "<text x='126' y='660' fill='#b7cad0' font-family='Arial' font-size='30'>A game worth discovering</text>"
                    + "</svg>";
            return svg.getBytes(StandardCharsets.UTF_8);
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private static String escape(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;").replace("'", "&apos;");
    }
}
