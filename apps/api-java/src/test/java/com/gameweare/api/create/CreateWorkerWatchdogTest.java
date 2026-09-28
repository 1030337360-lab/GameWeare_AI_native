package com.gameweare.api.create;

import com.gameweare.api.billing.TokenBillingService;
import com.gameweare.api.voucher.GenerationVoucherService;
import io.minio.MinioClient;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;

import static org.mockito.Mockito.*;

class CreateWorkerWatchdogTest {
    @Test
    void jobLockUsesWatchdogOverloadAndReleasesAfterUnclaimedMessage() throws Exception {
        RedissonClient redis = mock(RedissonClient.class);
        RLock lock = mock(RLock.class);
        when(redis.getLock("create:job:run:job-1")).thenReturn(lock);
        when(lock.tryLock(0, TimeUnit.SECONDS)).thenReturn(true);
        when(lock.isHeldByCurrentThread()).thenReturn(true);
        CreateWorker worker = new CreateWorker(mock(org.springframework.jdbc.core.JdbcTemplate.class),
                mock(TransactionTemplate.class), mock(CreateService.class), mock(TokenBillingService.class),
                mock(GenerationVoucherService.class), mock(MinioClient.class),
                null, mock(ArtifactValidator.class), null, "bucket");
        ReflectionTestUtils.setField(worker, "redisson", redis);
        worker.consume("job-1");
        verify(lock).tryLock(0, TimeUnit.SECONDS);
        verify(lock).unlock();
        verify(lock, never()).tryLock(anyLong(), anyLong(), any(TimeUnit.class));
    }
}
