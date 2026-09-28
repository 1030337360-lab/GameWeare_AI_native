package com.gameweare.api.create;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

import org.graalvm.polyglot.Context;
import org.graalvm.polyglot.PolyglotException;
import org.graalvm.polyglot.Source;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.springframework.stereotype.Component;

/** Syntax and packaging checks only: generated code is never executed by the API. */
@Component
public class ArtifactValidator {
    private static final Pattern CSS_RULE = Pattern.compile("(?s)([^{}]+)\\{([^{}]*)\\}");
    private static final Pattern DISPLAY_NONE = Pattern.compile("(?i)(?:^|;)\\s*display\\s*:\\s*none\\b");
    private static final Pattern DISPLAY_PROPERTY = Pattern.compile("(?i)(?:^|;)\\s*display\\s*:\\s*([^;]+)");
    public record Diagnostic(String code, String message, int scriptIndex, int line) {}
    public record Result(boolean ok, String format, List<Diagnostic> diagnostics, String normalizedHtml) {}

    public Result validate(String raw) {
        List<Diagnostic> errors = new ArrayList<>();
        if (raw == null) return failed("EMPTY", "HTML is required");
        String html = normalizeDocument(raw);
        int bytes = html.getBytes(StandardCharsets.UTF_8).length;
        if (bytes < 100) errors.add(new Diagnostic("TOO_SMALL", "A complete HTML game is required", 0, 0));
        if (bytes > 2_000_000) errors.add(new Diagnostic("TOO_LARGE", "HTML exceeds 2 MB", 0, 0));
        if (!html.toLowerCase(Locale.ROOT).contains("<html") || !html.toLowerCase(Locale.ROOT).contains("</html>"))
            errors.add(new Diagnostic("HTML_DOCUMENT", "A complete html element is required", 0, 0));
        if (bytes > 2_000_000 || !errors.isEmpty()) return new Result(false, "single-html", errors, "");

        Document doc = Jsoup.parse(html);
        if (doc.selectFirst("body") == null || doc.selectFirst("head") == null)
            errors.add(new Diagnostic("HTML_STRUCTURE", "head and body elements are required", 0, 0));
        if (doc.select("script").isEmpty())
            errors.add(new Diagnostic("SCRIPT_REQUIRED", "At least one inline script is required", 0, 0));
        if (!doc.select("script[src], link[href], iframe, object, embed, base").isEmpty())
            errors.add(new Diagnostic("EXTERNAL_RESOURCE", "External scripts, styles, frames and embedded content are not allowed", 0, 0));
        Element startScreen = doc.getElementById("start");
        Element gameScreen = doc.getElementById("game");
        if (startScreen != null && gameScreen != null && !startScreen.select("button").isEmpty()
                && hiddenAtLoad(doc, startScreen) && hiddenAtLoad(doc, gameScreen))
            errors.add(new Diagnostic("START_SCREEN_HIDDEN",
                    "Both #start and #game are hidden at load. Show the start controls before waiting for a click.", 0, 0));
        for (Element element : doc.getAllElements()) {
            for (var attribute : element.attributes()) {
                String name = attribute.getKey().toLowerCase(Locale.ROOT);
                String value = attribute.getValue().strip().toLowerCase(Locale.ROOT);
                if (name.startsWith("on") || value.startsWith("javascript:"))
                    errors.add(new Diagnostic("INLINE_HANDLER", "Use inline script blocks instead of event attributes or javascript URLs", 0, 0));
                if (name.equals("src") || name.equals("href") || name.equals("action")) {
                    if (value.startsWith("http:") || value.startsWith("https:") || value.startsWith("//"))
                        errors.add(new Diagnostic("EXTERNAL_RESOURCE", "Remote resources are not allowed", 0, 0));
                }
            }
        }
        int scriptIndex = 0;
        for (Element script : doc.select("script")) {
            scriptIndex++;
            String type = script.attr("type").toLowerCase(Locale.ROOT);
            if (!(type.isBlank() || type.equals("text/javascript") || type.equals("module"))) continue;
            String code = script.data();
            if (code.isBlank()) continue;
            try (Context context = Context.newBuilder("js").allowAllAccess(false).build()) {
                Source source = Source.newBuilder("js", code, "inline-script-" + scriptIndex + ".js")
                        .mimeType(type.equals("module") ? "application/javascript+module" : "application/javascript")
                        .buildLiteral();
                context.parse(source);
            } catch (PolyglotException e) {
                int line = e.getSourceLocation() == null ? 0 : e.getSourceLocation().getStartLine();
                errors.add(new Diagnostic(e.isSyntaxError() ? "JS_SYNTAX" : "JS_PARSE", safeMessage(e), scriptIndex, line));
            } catch (Exception e) {
                String detail = e.getMessage() == null ? "no diagnostic provided" : e.getMessage();
                errors.add(new Diagnostic("JS_PARSE", "JavaScript parser failed ("
                        + e.getClass().getSimpleName() + "): "
                        + detail.substring(0, Math.min(300, detail.length())), scriptIndex, 0));
            }
        }
        return new Result(errors.isEmpty(), "single-html", List.copyOf(errors), errors.isEmpty() ? html : "");
    }

    private static Result failed(String code, String message) {
        return new Result(false, "single-html", List.of(new Diagnostic(code, message, 0, 0)), "");
    }

    private static String normalizeDocument(String raw) {
        String text = raw.strip();
        String lower = text.toLowerCase(Locale.ROOT);
        int opening = lower.indexOf("<html");
        int closing = lower.lastIndexOf("</html>");
        if (opening < 0 || closing < opening) return text;
        int doctype = lower.lastIndexOf("<!doctype html", opening);
        if (doctype >= 0 && lower.substring(doctype, opening).matches("(?s)<!doctype html\\s*>\\s*"))
            opening = doctype;
        return text.substring(opening, closing + "</html>".length()).strip();
    }

    private static boolean hiddenAtLoad(Document doc, Element element) {
        String inlineStyle = element.attr("style");
        var inlineDisplay = DISPLAY_PROPERTY.matcher(inlineStyle);
        if (inlineDisplay.find()) return inlineDisplay.group(1).strip().toLowerCase(Locale.ROOT).matches("none(?:\\s*!important)?");
        for (Element style : doc.select("style")) {
            var rules = CSS_RULE.matcher(style.data());
            while (rules.find()) {
                if (!DISPLAY_NONE.matcher(rules.group(2)).find()) continue;
                for (String selector : rules.group(1).split(","))
                    if (selector.strip().equals("#" + element.id())) return true;
            }
        }
        return false;
    }

    private static String safeMessage(PolyglotException e) {
        String message = e.getMessage();
        if (message == null) return "Invalid JavaScript";
        return message.substring(0, Math.min(300, message.length()));
    }
}
