package com.gameweare.api.create;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CreationGuideModelTest {
    @Test void modelAutonomouslyReadsSkillAndReceivesConversationAndLatestBrief() throws Exception {
        ObjectMapper json=new ObjectMapper();
        List<String> requests=new ArrayList<>();
        HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        server.createContext("/responses",exchange -> {
            requests.add(new String(exchange.getRequestBody().readAllBytes(),StandardCharsets.UTF_8));
            Object output=requests.size()==1
                    ? Map.of("output",List.of(Map.of("type","function_call","name","read_creation_skill","call_id","skill-1",
                            "arguments","{\"id\":\"puzzle-design\"}")),"usage",Map.of("input_tokens",2,"output_tokens",1))
                    : Map.of("output_text","{\"reply\":\"每关连接所有星星，你希望可以撤销吗？\",\"brief\":{\"concept\":\"星座解谜\",\"questions\":[\"支持撤销吗？\"]}}",
                            "usage",Map.of("input_tokens",3,"output_tokens",2));
            byte[] bytes=json.writeValueAsBytes(output);
            exchange.getResponseHeaders().set("Content-Type","application/json"); exchange.sendResponseHeaders(200,bytes.length);
            try(var body=exchange.getResponseBody()){body.write(bytes);}
        });
        server.start();
        String oldHosts=LlmClient.allowedHosts; boolean oldPrivate=CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts="127.0.0.1"; CreateService.privateLlmEndpointsAllowed=true;
            var reply=new CreationGuideModel(new CreationSkillRepository()).respond("http://127.0.0.1:"+server.getAddress().getPort(),
                    "mock","test",List.of(Map.of("role","user","content","我想做星座解谜")),"{}","每关连完所有星星","init");
            assertEquals(List.of("puzzle-design"),reply.skills()); assertFalse(reply.brief().ready());
            assertEquals(5,reply.inputTokens()); assertEquals(3,reply.outputTokens());
            assertTrue(requests.get(1).contains("function_call_output"));
            assertTrue(requests.get(1).contains("先弄清玩家改变什么"));
            assertTrue(requests.get(1).contains("我想做星座解谜"));
            assertTrue(requests.get(1).contains("每关连完所有星星"));
        } finally { LlmClient.allowedHosts=oldHosts; CreateService.privateLlmEndpointsAllowed=oldPrivate; server.stop(0); }
    }
    @Test void skillsCannotReadArbitraryFilesAndBriefMustBeBounded() throws Exception {
        var repository=new CreationSkillRepository();
        assertEquals(5,repository.list().size());
        assertThrows(IllegalArgumentException.class,()->repository.read("../../application.yml"));
        var json=new ObjectMapper();
        assertThrows(IllegalArgumentException.class,()->GameBrief.parse(json.readTree("{\"concept\":\""+"x".repeat(241)+"\"}")));
        GameBrief brief=GameBrief.parse(json.readTree("{\"concept\":\"主题\",\"coreLoop\":\"循环\",\"controls\":\"操作\",\"rules\":\"规则\",\"victory\":\"目标\"}"));
        assertTrue(brief.ready()); assertTrue(brief.generationPrompt().contains("核心玩法循环：循环"));
        assertEquals("主题", CreateService.title(brief.generationPrompt()));
    }
}
