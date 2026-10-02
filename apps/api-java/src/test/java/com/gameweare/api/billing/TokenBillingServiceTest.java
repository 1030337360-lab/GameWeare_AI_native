package com.gameweare.api.billing;

import com.gameweare.api.billing.dao.TokenAccountMapper;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Reserve, settle and refund rules must remain unchanged when the SQL gateway is replaced. */
class TokenBillingServiceTest {
    private final TokenAccountMapper mapper = mock(TokenAccountMapper.class);
    private final TokenBillingService service = new TokenBillingService(mapper);

    @BeforeEach void noLedgerByDefault() {
        when(mapper.findLedger("job-1", "RESERVE")).thenReturn(null);
        when(mapper.findLedger("job-1", "SETTLE")).thenReturn(null);
        when(mapper.findLedger("job-1", "REFUND")).thenReturn(null);
    }

    private void account(long balance, long reserved) {
        when(mapper.lockAccount("user-1")).thenReturn(Map.of("balance", balance, "reserved", reserved, "version", 1L));
    }

    private void ledger(String type, String userId, long amount) {
        when(mapper.findLedger("job-1", type)).thenReturn(Map.of("user_id", userId, "amount", amount));
    }

    @Test void reserveMovesBalanceAndWritesLedger() {
        account(1000, 0);
        var out = service.reserve("user-1", "job-1", 300);
        assertEquals(700, out.balance());
        assertEquals(300, out.reserved());
        verify(mapper).reserve("user-1", 300);
        verify(mapper).insertLedger(anyString(), eq("user-1"), eq("job-1"), eq("RESERVE"), eq(300L));
    }

    @Test void reserveIsIdempotentForSameRequest() {
        account(700, 300); ledger("RESERVE", "user-1", 300);
        assertEquals(700, service.reserve("user-1", "job-1", 300).balance());
        verify(mapper, never()).reserve(anyString(), eq(300L));
    }

    @Test void reserveRejectsConflictingRetry() {
        account(700, 300); ledger("RESERVE", "user-1", 500);
        assertEquals(HttpStatus.CONFLICT, status(() -> service.reserve("user-1", "job-1", 300)));
        verify(mapper, never()).reserve(anyString(), eq(300L));
    }

    @Test void reserveRejectsInsufficientBalance() {
        account(100, 0);
        assertEquals(HttpStatus.PAYMENT_REQUIRED, status(() -> service.reserve("user-1", "job-1", 300)));
        verify(mapper, never()).reserve(anyString(), eq(300L));
    }

    @Test void settleChargesUsageAndRefundsRemainder() {
        account(700, 300); ledger("RESERVE", "user-1", 300);
        var out = service.settle("user-1", "job-1", 120);
        assertEquals(880, out.balance()); assertEquals(0, out.reserved());
        verify(mapper).release("user-1", 300, 180);
        verify(mapper).insertLedger(anyString(), eq("user-1"), eq("job-1"), eq("SETTLE"), eq(120L));
        verify(mapper).insertLedger(anyString(), eq("user-1"), eq("job-1"), eq("REFUND"), eq(180L));
    }

    @Test void settleIsIdempotentForSameAmount() {
        account(700, 300); ledger("RESERVE", "user-1", 300); ledger("SETTLE", "user-1", 120);
        assertEquals(700, service.settle("user-1", "job-1", 120).balance());
        verify(mapper, never()).release(anyString(), eq(300L), eq(180L));
    }

    @Test void settleAfterRefundIsRejected() {
        account(1000, 0); ledger("RESERVE", "user-1", 300); ledger("REFUND", "user-1", 300);
        assertEquals(HttpStatus.CONFLICT, status(() -> service.settle("user-1", "job-1", 120)));
    }

    @Test void settleRejectsChargeAboveReservation() {
        account(700, 300); ledger("RESERVE", "user-1", 300);
        assertEquals(HttpStatus.CONFLICT, status(() -> service.settle("user-1", "job-1", 400)));
    }

    @Test void refundReturnsReservationOnce() {
        account(700, 300); ledger("RESERVE", "user-1", 300);
        var out = service.refund("user-1", "job-1");
        assertEquals(1000, out.balance()); assertEquals(0, out.reserved());
        verify(mapper).release("user-1", 300, 300);
        verify(mapper).insertLedger(anyString(), eq("user-1"), eq("job-1"), eq("REFUND"), eq(300L));
    }

    @Test void refundIsIdempotentAfterRefund() {
        account(1000, 0); ledger("RESERVE", "user-1", 300); ledger("REFUND", "user-1", 300);
        assertEquals(1000, service.refund("user-1", "job-1").balance());
        verify(mapper, never()).release(anyString(), eq(300L), eq(300L));
    }

    @Test void refundWithoutReservationIsNoop() {
        account(1000, 0);
        assertEquals(1000, service.refund("user-1", "job-1").balance());
        verify(mapper, never()).release(anyString(), eq(300L), eq(300L));
    }

    @Test void invalidAmountsAndJobIdsAreRejected() {
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
