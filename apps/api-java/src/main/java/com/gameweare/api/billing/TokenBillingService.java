package com.gameweare.api.billing;

import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/** MySQL is authoritative. Every mutation holds the account row lock until the ledger and balances commit. */
@Service
public class TokenBillingService {
    private final JdbcTemplate jdbc;

    public TokenBillingService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Account account(String userId) {
        var rows = jdbc.query("SELECT balance,reserved,version FROM token_accounts WHERE user_id=?",
                (rs, ignored) -> new Account(rs.getLong(1), rs.getLong(2), rs.getLong(3)), userId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Token account not found");
        return rows.get(0);
    }

    @Transactional
    public Account reserve(String userId, String jobId, long amount) {
        requirePositive(amount);
        requireJobId(jobId);
        Account account = lockedAccount(userId);
        Ledger reserve = ledger(jobId, "RESERVE");
        if (reserve != null) {
            if (!reserve.userId().equals(userId) || reserve.amount() != amount)
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Reservation idempotency conflict");
            return account;
        }
        if (account.balance() < amount) throw new ResponseStatusException(HttpStatus.PAYMENT_REQUIRED, "Insufficient tokens");
        jdbc.update("UPDATE token_accounts SET balance=balance-?,reserved=reserved+?,version=version+1 WHERE user_id=?",
                amount, amount, userId);
        insert(jobId, userId, "RESERVE", amount);
        return new Account(account.balance() - amount, Math.addExact(account.reserved(), amount), account.version() + 1);
    }

    @Transactional
    public Account settle(String userId, String jobId, long actualAmount) {
        if (actualAmount < 0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Negative token charge");
        requireJobId(jobId);
        Account account = lockedAccount(userId);
        Ledger reserve = ownedReservation(userId, jobId);
        Ledger settled = ledger(jobId, "SETTLE");
        if (settled != null) {
            if (settled.amount() != actualAmount)
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Settlement idempotency conflict");
            return account;
        }
        if (ledger(jobId, "REFUND") != null)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Reservation already refunded");
        if (actualAmount > reserve.amount())
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Charge exceeds reservation");
        long remainder = reserve.amount() - actualAmount;
        if (account.reserved() < reserve.amount()) throw new IllegalStateException("Reserved token invariant violated");
        jdbc.update("UPDATE token_accounts SET reserved=reserved-?,balance=balance+?,version=version+1 WHERE user_id=?",
                reserve.amount(), remainder, userId);
        insert(jobId, userId, "SETTLE", actualAmount);
        if (remainder > 0) insert(jobId, userId, "REFUND", remainder);
        return new Account(Math.addExact(account.balance(), remainder), account.reserved() - reserve.amount(), account.version() + 1);
    }

    @Transactional
    public Account refund(String userId, String jobId) {
        requireJobId(jobId);
        Account account = lockedAccount(userId);
        Ledger reserve = ledger(jobId, "RESERVE");
        if (reserve == null) return account;
        if (!reserve.userId().equals(userId)) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Wrong account");
        if (ledger(jobId, "REFUND") != null || ledger(jobId, "SETTLE") != null) return account;
        if (account.reserved() < reserve.amount()) throw new IllegalStateException("Reserved token invariant violated");
        jdbc.update("UPDATE token_accounts SET reserved=reserved-?,balance=balance+?,version=version+1 WHERE user_id=?",
                reserve.amount(), reserve.amount(), userId);
        insert(jobId, userId, "REFUND", reserve.amount());
        return new Account(Math.addExact(account.balance(), reserve.amount()),
                account.reserved() - reserve.amount(), account.version() + 1);
    }

    private Account lockedAccount(String userId) {
        var rows = jdbc.query("SELECT balance,reserved,version FROM token_accounts WHERE user_id=? FOR UPDATE",
                (rs, ignored) -> new Account(rs.getLong(1), rs.getLong(2), rs.getLong(3)), userId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Token account not found");
        return rows.get(0);
    }

    private Ledger ownedReservation(String userId, String jobId) {
        Ledger reserve = ledger(jobId, "RESERVE");
        if (reserve == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "Reservation not found");
        if (!reserve.userId().equals(userId)) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Wrong account");
        return reserve;
    }

    private Ledger ledger(String jobId, String type) {
        List<Ledger> rows = jdbc.query("SELECT user_id,amount FROM token_ledger WHERE job_id=? AND entry_type=?",
                (rs, ignored) -> new Ledger(rs.getString(1), rs.getLong(2)), jobId, type);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private void insert(String jobId, String userId, String type, long amount) {
        jdbc.update("INSERT INTO token_ledger(id,user_id,job_id,entry_type,amount,created_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
                UUID.randomUUID().toString(), userId, jobId, type, amount);
    }

    private static void requirePositive(long amount) {
        if (amount <= 0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Reservation must be positive");
    }

    private static void requireJobId(String jobId) {
        if (jobId == null || jobId.isBlank() || jobId.length() > 36)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid job ID");
    }

    public record Account(long balance, long reserved, long version) {}
    private record Ledger(String userId, long amount) {}
}
