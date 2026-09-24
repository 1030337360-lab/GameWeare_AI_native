package com.gameweare.api.billing;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Reserve/settle/refund consistency of the MySQL-authoritative token ledger. */
class TokenBillingServiceTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final TokenBillingService service = new TokenBillingService(jdbc);
    private final Map<String, ResultSet> ledgerRows = new HashMap<>();

    @BeforeEach
    @SuppressWarnings("unchecked")
    void stubLedgerQuery() {
        when(jdbc.query(contains("token_ledger"), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(invocation -> {
                    ResultSet rs = ledgerRows.get(invocation.getArgument(3, String.class));
                    if (rs == null) return List.of();
                    return List.of(((RowMapper<Object>) invocation.getArgument(1)).mapRow(rs, 0));
                });
    }

    private void stubLedger(String type, String userId, long amount) throws SQLException {
        ResultSet rs = mock(ResultSet.class);
        when(rs.getString(1)).thenReturn(userId);
        when(rs.getLong(2)).thenReturn(amount);
        ledgerRows.put(type, rs);
    }

    private void stubAccount(long balance, long reserved) throws SQLException {
        ResultSet rs = mock(ResultSet.class);
        when(rs.getLong(1)).thenReturn(balance);
        when(rs.getLong(2)).thenReturn(reserved);
        when(rs.getLong(3)).thenReturn(1L);
        when(jdbc.query(contains("token_accounts"), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(invocation -> List.of(((RowMapper<Object>) invocation.getArgument(1)).mapRow(rs, 0)));
    }

    @Test
    void reserveMovesBalanceAndWritesLedger() throws SQLException {
        stubAccount(1000, 0);

        TokenBillingService.Account out = service.reserve("user-1", "job-1", 300);

        assertEquals(700, out.balance());
        assertEquals(300, out.reserved());
        verify(jdbc).update("UPDATE token_accounts SET balance=balance-?,reserved=reserved+?,version=version+1 WHERE user_id=?",
                300L, 300L, "user-1");
        verify(jdbc).update(contains("token_ledger"), any(), eq("user-1"), eq("job-1"), eq("RESERVE"), eq(300L));
    }

    @Test
    void reserveIsIdempotentForSameRequest() throws SQLException {
        stubAccount(700, 300);
        stubLedger("RESERVE", "user-1", 300);

        TokenBillingService.Account out = service.reserve("user-1", "job-1", 300);

        assertEquals(700, out.balance());
        assertEquals(300, out.reserved());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void reserveRejectsConflictingIdempotentRetry() throws SQLException {
        stubAccount(700, 300);
        stubLedger("RESERVE", "user-1", 500);

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.reserve("user-1", "job-1", 300));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void reserveRejectsInsufficientBalance() throws SQLException {
        stubAccount(100, 0);

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.reserve("user-1", "job-1", 300));

        assertEquals(HttpStatus.PAYMENT_REQUIRED, error.getStatusCode());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void settleChargesUsageAndRefundsRemainder() throws SQLException {
        stubAccount(700, 300);
        stubLedger("RESERVE", "user-1", 300);

        TokenBillingService.Account out = service.settle("user-1", "job-1", 120);

        assertEquals(880, out.balance());
        assertEquals(0, out.reserved());
        verify(jdbc).update("UPDATE token_accounts SET reserved=reserved-?,balance=balance+?,version=version+1 WHERE user_id=?",
                300L, 180L, "user-1");
        verify(jdbc).update(contains("token_ledger"), any(), eq("user-1"), eq("job-1"), eq("SETTLE"), eq(120L));
        verify(jdbc).update(contains("token_ledger"), any(), eq("user-1"), eq("job-1"), eq("REFUND"), eq(180L));
    }

    @Test
    void settleIsIdempotentForSameAmount() throws SQLException {
        stubAccount(700, 300);
        stubLedger("RESERVE", "user-1", 300);
        stubLedger("SETTLE", "user-1", 120);

        TokenBillingService.Account out = service.settle("user-1", "job-1", 120);

        assertEquals(700, out.balance());
        assertEquals(300, out.reserved());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void settleAfterRefundIsRejected() throws SQLException {
        stubAccount(1000, 0);
        stubLedger("RESERVE", "user-1", 300);
        stubLedger("REFUND", "user-1", 300);

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.settle("user-1", "job-1", 120));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void settleRejectsChargeAboveReservation() throws SQLException {
        stubAccount(700, 300);
        stubLedger("RESERVE", "user-1", 300);

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.settle("user-1", "job-1", 400));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void refundReturnsReservationOnce() throws SQLException {
        stubAccount(700, 300);
        stubLedger("RESERVE", "user-1", 300);

        TokenBillingService.Account out = service.refund("user-1", "job-1");

        assertEquals(1000, out.balance());
        assertEquals(0, out.reserved());
        verify(jdbc).update("UPDATE token_accounts SET reserved=reserved-?,balance=balance+?,version=version+1 WHERE user_id=?",
                300L, 300L, "user-1");
        verify(jdbc).update(contains("token_ledger"), any(), eq("user-1"), eq("job-1"), eq("REFUND"), eq(300L));
    }

    @Test
    void refundIsIdempotentAfterRefund() throws SQLException {
        stubAccount(1000, 0);
        stubLedger("RESERVE", "user-1", 300);
        stubLedger("REFUND", "user-1", 300);

        TokenBillingService.Account out = service.refund("user-1", "job-1");

        assertEquals(1000, out.balance());
        assertEquals(0, out.reserved());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void refundWithoutReservationIsNoop() throws SQLException {
        stubAccount(1000, 0);

        TokenBillingService.Account out = service.refund("user-1", "job-1");

        assertEquals(1000, out.balance());
        assertEquals(0, out.reserved());
        verify(jdbc, never()).update(anyString(), any(Object[].class));
    }

    @Test
    void invalidAmountsAndJobIdsAreRejected() {
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.reserve("user-1", "job-1", 0)));
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.reserve("user-1", "job-1", -5)));
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.reserve("user-1", "", 10)));
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.reserve("user-1", "x".repeat(37), 10)));
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.settle("user-1", "job-1", -1)));
    }

    private org.springframework.http.HttpStatusCode status(Runnable call) {
        return assertThrows(ResponseStatusException.class, call::run).getStatusCode();
    }
}
