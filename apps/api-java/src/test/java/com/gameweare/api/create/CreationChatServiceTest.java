package com.gameweare.api.create;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.gameweare.api.create.dao.CreationChatMapper;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

class CreationChatServiceTest {
    private static final String ID="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", REQUEST="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
    private final CreationChatMapper chats=mock(CreationChatMapper.class);
    private final CreateService creation=mock(CreateService.class);
    private final CreationGuideModel model=mock(CreationGuideModel.class);
    private final StringRedisTemplate redis=mock(StringRedisTemplate.class);
    private final PlatformTransactionManager manager=mock(PlatformTransactionManager.class);
    private final CreationChatService service=new CreationChatService(chats, creation, model, new TransactionTemplate(manager), redis);

    private Map<String,Object> row(String status, int revision, boolean ready) throws Exception {
        Map<String,Object> row=new HashMap<>();
        row.put("id",ID); row.put("status",status); row.put("revision",revision); row.put("create_type","init"); row.put("funding_mode","byok");
        if (ready) row.put("brief_json", new ObjectMapper().writeValueAsString(Map.of("concept","星空跑酷", "coreLoop","跳跃躲避获取分数",
                "controls","空格跳跃", "rules","撞击结束，可重试", "victory","达到100分", "questions",List.of())));
        when(chats.find(ID,"owner")).thenReturn(row);
        when(chats.lock(ID,"owner")).thenReturn(row);
        when(chats.messages(ID)).thenReturn(List.of());
        return row;
    }
    @Test void anotherUserCannotReadOrSend() {
        assertEquals(404, assertThrows(ResponseStatusException.class, () -> service.get("other",ID)).getStatusCode().value());
        assertThrows(ResponseStatusException.class, () -> service.turn("other",ID,new CreationChatController.Turn("hello",REQUEST,0)));
        verifyNoInteractions(model, creation, redis);
    }
    @Test void skillIdsArePlainStringArraysForTheHttpSerializer() throws Exception {
        row("draft",1,true);
        when(chats.messages(ID)).thenReturn(List.of(Map.of("request_id",REQUEST,"role","assistant", "content","选择操作方式",
                "skill_ids_json","[\"game-interview\"]","sequence_no",1)));
        List<?> messages=(List<?>)service.get("owner",ID).get("messages");
        assertEquals(List.of("game-interview"),((Map<?,?>)messages.get(0)).get("skillIds"));
    }
    @Test void unreviewedOrStaleBriefCannotCreateGame() throws Exception {
        row("draft",2,true);
        assertEquals(409, assertThrows(ResponseStatusException.class, () -> service.confirm("owner",ID,1)).getStatusCode().value());
        row("replying",2,true);
        assertThrows(ResponseStatusException.class, () -> service.confirm("owner",ID,2));
        row("draft",0,false);
        assertThrows(ResponseStatusException.class, () -> service.confirm("owner",ID,0));
        verifyNoInteractions(creation);
    }
    @Test void confirmationUsesReactAndSameFundingAndIsRepeatable() throws Exception {
        Map<String,Object> row=row("draft",2,true);
        row.put("funding_mode","voucher"); row.put("voucher_id",REQUEST);
        Map<String,Object> job=Map.of("id","job-1","agentMode","react");
        when(creation.create(eq("owner"),any(),eq("chat:"+ID))).thenReturn(job);
        when(chats.confirm(ID,"owner",2,"job-1")).thenReturn(1);
        assertEquals(job,service.confirm("owner",ID,2));
        ArgumentCaptor<CreateController.JobRequest> request=ArgumentCaptor.forClass(CreateController.JobRequest.class);
        verify(creation).create(eq("owner"),request.capture(),eq("chat:"+ID));
        assertEquals("react",request.getValue().agentMode());
        assertEquals("voucher",request.getValue().fundingMode());
        assertEquals(REQUEST,request.getValue().voucherId());
        assertTrue(request.getValue().prompt().contains("空格跳跃"));
        assertTrue(request.getValue().prompt().length()<4000);
        row.put("status","confirmed"); row.put("job_id","job-1");
        when(creation.job("owner","job-1")).thenReturn(job);
        assertEquals(job,service.confirm("owner",ID,0));
        verify(creation,times(1)).create(any(),any(),any());
    }
    @Test void duplicateTurnDoesNotCallModelAndRejectsChangedContent() throws Exception {
        row("draft",1,true);
        when(chats.completedRequest(ID,REQUEST)).thenReturn(1);
        when(chats.requestMessage(ID,REQUEST)).thenReturn("跑酷");
        assertEquals(1,service.turn("owner",ID,new CreationChatController.Turn("跑酷",REQUEST,0)).get("revision"));
        assertEquals(409,assertThrows(ResponseStatusException.class, () -> service.turn("owner",ID,
                new CreationChatController.Turn("射击",REQUEST,0))).getStatusCode().value());
        verifyNoInteractions(model,creation,redis);
    }
    @Test void providerFailureReleasesLeaseWithoutPersistingTurn() throws Exception {
        row("draft",0,false);
        when(creation.configRow("owner")).thenReturn(Map.of("model","mock"));
        when(creation.configRowForJob(eq("owner"),any())).thenReturn(Map.of("base_url","https://example.test","model","mock"));
        when(creation.keyFor(any())).thenReturn("secret");
        when(redis.execute(any(org.springframework.data.redis.core.script.RedisScript.class),anyList())).thenReturn(1L);
        when(chats.claim(eq(ID),eq("owner"),anyString(),eq(0))).thenReturn(1);
        when(model.respond(anyString(),anyString(),anyString(),anyList(),anyString(),anyString(),anyString()))
                .thenThrow(new IllegalStateException("provider exposed secret"));
        var error=assertThrows(ResponseStatusException.class, () -> service.turn("owner",ID,new CreationChatController.Turn("跑酷",REQUEST,0)));
        assertEquals(502,error.getStatusCode().value()); assertFalse(error.getReason().contains("secret"));
        ArgumentCaptor<String> lease=ArgumentCaptor.forClass(String.class);
        verify(chats).claim(eq(ID),eq("owner"),lease.capture(),eq(0));
        assertNotEquals(REQUEST,lease.getValue());
        verify(chats).release(ID,"owner",lease.getValue());
        verify(chats,never()).message(any(),any(),any(),any(),any(),any(),anyInt(),anyLong(),anyLong());
        verify(creation,never()).create(any(),any(),any());
    }
    @Test void successfulTurnCommitsBothMessagesAndBriefWithoutGeneration() throws Exception {
        Map<String,Object> stored=row("draft",0,false);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        when(creation.configRow("owner")).thenReturn(Map.of("model","mock"));
        when(creation.configRowForJob(eq("owner"),any())).thenReturn(Map.of("base_url","https://example.test","model","mock"));
        when(creation.keyFor(any())).thenReturn("secret");
        when(redis.execute(any(org.springframework.data.redis.core.script.RedisScript.class),anyList())).thenReturn(1L);
        when(chats.claim(eq(ID),eq("owner"),anyString(),eq(0))).thenReturn(1);
        GameBrief brief=GameBrief.parse(new ObjectMapper().readTree("{\"concept\":\"跑酷\",\"questions\":[\"如何跳跃？\"]}"));
        when(model.respond(anyString(),anyString(),anyString(),anyList(),anyString(),anyString(),anyString()))
                .thenReturn(new CreationGuideModel.Reply("你希望用空格跳跃吗？",brief,List.of("arcade-design"),12,20));
        when(chats.finish(eq(ID),eq("owner"),anyString(),eq(0),anyString())).thenAnswer(invocation -> {
            stored.put("revision",1); stored.put("brief_json",invocation.getArgument(4)); return 1;
        });
        assertEquals(1,service.turn("owner",ID,new CreationChatController.Turn("跑酷",REQUEST,0)).get("revision"));
        verify(chats).message(anyString(),eq(ID),eq(REQUEST),eq("user"),eq("跑酷"),eq("[]"),eq(0),eq(0L),eq(0L));
        verify(chats).message(anyString(),eq(ID),eq(REQUEST),eq("assistant"),anyString(),eq("[\"arcade-design\"]"),eq(1),eq(12L),eq(20L));
        verify(manager).commit(any());
        verify(creation,never()).create(any(),any(),any());
    }
}
