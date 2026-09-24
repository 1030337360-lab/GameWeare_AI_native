package com.gameweare.api.create;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import org.junit.jupiter.api.Test;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.server.ResponseStatusException;

import com.gameweare.api.billing.TokenBillingService;

import io.minio.MinioClient;

/** Unit coverage for the plan and decentralized creator-approval workflows. */
class CreateServiceWorkflowTest {
    private static final String PLAN_JSON = """
        {"plan":[
          {"id":"s1","title":"Core loop","goal":"Move and shoot","toolFamily":"canvas","expectedOutput":"loop","acceptanceCheckRefs":["c1"]},
          {"id":"s2","title":"Enemies","goal":"Spawn waves","toolFamily":"canvas","expectedOutput":"enemies","acceptanceCheckRefs":["c2"]},
          {"id":"s3","title":"Score","goal":"Track score","toolFamily":"dom","expectedOutput":"hud","acceptanceCheckRefs":["c3"]}],
         "risks":["Performance on low-end devices"],
         "acceptanceChecks":[{"id":"c1","description":"Player moves","type":"manual","severity":"high"}]}
        """;
    private static final String CANDIDATES_JSON = """
        {"candidates":[
          {"candidateId":"c1","title":"Neon runner","conceptSummary":"Fast runner","expertRole":"Gameplay","expertDomain":"Arcade","expertIntro":"Hi","styleTags":["neon"],"staticHtml":"<html><body>1</body></html>"},
          {"candidateId":"c2","title":"Pixel dungeon","conceptSummary":"Crawler","expertRole":"Systems","expertDomain":"RPG","expertIntro":"Yo","styleTags":["pixel"],"staticHtml":"<html><body>2</body></html>"},
          {"candidateId":"c3","title":"Space shooter","conceptSummary":"Shooter","expertRole":"Combat","expertDomain":"Action","expertIntro":"Hey","styleTags":["space"],"staticHtml":"<html><body>3</body></html>"}]}
        """;

    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final TokenBillingService billing = mock(TokenBillingService.class);
    private final CreateService service =
            new CreateService(db, billing, mock(MinioClient.class), "test-secret-that-is-32-chars-long", "bucket");

    @Test
    void planPreviewReturnsStoredPlan() {
        jobRow("plan", "planning");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_plan", "preview_json", PLAN_JSON)));

        Map<String, Object> out = service.planPreview("user-1", "job-1");

        assertEquals("job-1", out.get("runId"));
        assertEquals("job-1", out.get("jobId"));
        assertEquals("awaiting_plan", out.get("phase"));
        @SuppressWarnings("unchecked")
        Map<String, Object> preview = (Map<String, Object>) out.get("planPreview");
        assertEquals(3, ((List<?>) preview.get("plan")).size());
        assertEquals(1, ((List<?>) preview.get("acceptanceChecks")).size());
    }

    @Test
    void planPreviewRejectsNonPlanRun() {
        jobRow("chat", "generating");

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.planPreview("user-1", "job-1"));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
    }

    @Test
    void planPreviewMissingWorkflowIsNotFound() {
        jobRow("plan", "generating");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1"))).thenReturn(List.of());

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.planPreview("user-1", "job-1"));

        assertEquals(HttpStatus.NOT_FOUND, error.getStatusCode());
    }

    @Test
    void unknownRunIsNotFound() {
        when(db.queryForMap(anyString(), any(Object[].class))).thenThrow(new EmptyResultDataAccessException(1));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.planPreview("user-1", "missing"));

        assertEquals(HttpStatus.NOT_FOUND, error.getStatusCode());
    }

    @Test
    void planDecisionRejectCancelsRunRefundsAndDropsDraftProject() {
        jobRow("plan", "planning");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_plan", "preview_json", PLAN_JSON)));
        stubJobReads("canceled");
        when(db.update(anyString(), any(Object[].class))).thenReturn(1);

        Map<String, Object> out = service.planDecision("user-1", "job-1", "rejected");

        assertEquals("canceled", out.get("status"));
        verify(db).update(contains("status='canceled'"), eq("job-1"));
        verify(db).update("UPDATE create_job_workflows SET phase='rejected' WHERE job_id=?", "job-1");
        verify(db).update(contains("create_projects SET status='deleted'"), eq("p1"));
        verify(billing).refund("user-1", "job-1");
    }

    @Test
    void planDecisionAcceptRequeuesJobThroughOutbox() {
        jobRow("plan", "planning");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_plan", "preview_json", PLAN_JSON)));
        stubJobReads("pending");
        when(db.update(anyString(), any(Object[].class))).thenReturn(1);

        Map<String, Object> out = service.planDecision("user-1", "job-1", "accepted");

        assertEquals("pending", out.get("status"));
        verify(db).update("UPDATE create_job_workflows SET phase='approved' WHERE job_id=?", "job-1");
        verify(db).update(contains("status='pending'"), eq("job-1"));
        verify(db).update(contains("ON DUPLICATE KEY UPDATE"), any(), eq("job-1"), eq("job.created"), eq("{}"));
        verify(billing, never()).refund(any(), any());
    }

    @Test
    void planDecisionRequiresAwaitingPhase() {
        jobRow("plan", "planning");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "approved", "preview_json", PLAN_JSON)));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.planDecision("user-1", "job-1", "accepted"));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verify(db, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void planDecisionRejectsInvalidChoice() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.planDecision("user-1", "job-1", "maybe"));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
        verifyNoInteractions(db);
    }

    @Test
    void decentralizedPreviewsReturnsCandidates() {
        jobRow("decentralized", "reviewing");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_selection", "preview_json", CANDIDATES_JSON)));

        Map<String, Object> out = service.decentralizedPreviews("user-1", "job-1");

        assertEquals("awaiting_selection", out.get("phase"));
        assertEquals(null, out.get("selectedCandidateId"));
        assertEquals(3, ((List<?>) out.get("candidates")).size());
    }

    @Test
    void selectCandidateMarksSelection() {
        jobRow("decentralized", "reviewing");
        Map<String, Object> before = row("phase", "awaiting_selection", "preview_json", CANDIDATES_JSON);
        Map<String, Object> after = row("phase", "candidate_selected", "preview_json", CANDIDATES_JSON, "selected_candidate_id", "c2");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(before), List.of(after));

        Map<String, Object> out = service.selectCandidate("user-1", "job-1", "c2");

        assertEquals("candidate_selected", out.get("phase"));
        assertEquals("c2", out.get("selectedCandidateId"));
        verify(db).update("UPDATE create_job_workflows SET selected_candidate_id=?,phase='candidate_selected' WHERE job_id=?", "c2", "job-1");
    }

    @Test
    void selectCandidateRejectsUnknownCandidate() {
        jobRow("decentralized", "reviewing");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_selection", "preview_json", CANDIDATES_JSON)));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.selectCandidate("user-1", "job-1", "zz"));

        assertEquals(HttpStatus.NOT_FOUND, error.getStatusCode());
        verify(db, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void confirmCandidateRequiresSelectionFirst() {
        jobRow("decentralized", "reviewing");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_selection", "preview_json", CANDIDATES_JSON)));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.confirmCandidate("user-1", "job-1", "accepted"));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verify(db, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void confirmCandidateAcceptedReplacesPreviewWithSelectedCandidate() {
        jobRow("decentralized", "reviewing");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "candidate_selected", "preview_json", CANDIDATES_JSON,
                        "selected_candidate_id", "c2")));
        stubJobReads("pending");
        when(db.update(anyString(), any(Object[].class))).thenReturn(1);

        Map<String, Object> out = service.confirmCandidate("user-1", "job-1", "accepted");

        assertEquals("pending", out.get("status"));
        verify(db).update(eq("UPDATE create_job_workflows SET phase='approved',preview_json=? WHERE job_id=?"),
                contains("\"candidateId\":\"c2\""), eq("job-1"));
        verify(db).update(contains("status='pending'"), eq("job-1"));
        verify(db).update(contains("ON DUPLICATE KEY UPDATE"), any(), eq("job-1"), eq("job.created"), eq("{}"));
    }

    @Test
    void confirmCandidateRejectedCancelsAndRefunds() {
        jobRow("decentralized", "reviewing");
        when(db.queryForList(contains("create_job_workflows"), eq("job-1")))
                .thenReturn(List.of(row("phase", "awaiting_selection", "preview_json", CANDIDATES_JSON)));
        stubJobReads("canceled");
        when(db.update(anyString(), any(Object[].class))).thenReturn(1);

        Map<String, Object> out = service.confirmCandidate("user-1", "job-1", "rejected");

        assertEquals("canceled", out.get("status"));
        verify(db).update(contains("status='canceled'"), eq("job-1"));
        verify(db).update("UPDATE create_job_workflows SET phase='rejected' WHERE job_id=?", "job-1");
        verify(billing).refund("user-1", "job-1");
    }

    private void jobRow(String mode, String status) {
        when(db.queryForMap(contains("agent_mode"), eq("job-1"), eq("user-1")))
                .thenReturn(row("agent_mode", mode, "status", status, "project_id", "p1",
                        "create_type", "init", "game_id", null));
    }

    private void stubJobReads(String status) {
        when(db.queryForMap(startsWith("SELECT * FROM create_jobs"), eq("job-1"), eq("user-1")))
                .thenReturn(row("id", "job-1", "status", status, "prompt", "make a game",
                        "agent_mode", "plan", "project_id", "p1", "game_id", null));
        when(db.queryForObject(anyString(), eq(Integer.class), any(Object[].class))).thenReturn(1);
        when(db.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());
    }

    private static Map<String, Object> row(Object... pairs) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) map.put((String) pairs[i], pairs[i + 1]);
        return map;
    }
}
