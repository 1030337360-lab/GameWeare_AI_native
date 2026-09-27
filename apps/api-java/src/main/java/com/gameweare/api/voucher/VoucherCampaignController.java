package com.gameweare.api.voucher;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/voucher-campaigns")
public class VoucherCampaignController {
    private final VoucherCampaignService campaigns;
    public VoucherCampaignController(VoucherCampaignService campaigns) { this.campaigns = campaigns; }

    @GetMapping
    public List<Map<String, Object>> list() { return campaigns.list(); }

    @PostMapping("/{id}/claim")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> claim(@PathVariable String id, @RequestAttribute("userId") String userId) {
        return campaigns.claim(id, userId);
    }

    @GetMapping("/{id}/claims/me")
    public Map<String, Object> mine(@PathVariable String id, @RequestAttribute("userId") String userId) {
        return campaigns.mine(id, userId);
    }

    @GetMapping("/{id}/claims/{reservationId}")
    public Map<String, Object> reservation(@PathVariable String id, @PathVariable String reservationId,
                                            @RequestAttribute("userId") String userId) {
        return campaigns.reservation(id, userId, reservationId);
    }
}

@RestController
@RequestMapping("/maintenance/voucher-campaigns")
class VoucherCampaignMaintenanceController {
    private final VoucherCampaignService campaigns;
    VoucherCampaignMaintenanceController(VoucherCampaignService campaigns) { this.campaigns = campaigns; }
    record NewCampaign(String title, Instant startsAt, Instant endsAt, int stock) {}

    @GetMapping
    public List<Map<String, Object>> list() { return campaigns.list(); }

    @PostMapping
    public Map<String, Object> create(@RequestBody NewCampaign input) { return campaigns.create(input); }

    @GetMapping("/{id}/reconcile")
    public Map<String, Object> reconcile(@PathVariable String id) { return campaigns.reconcile(id); }
}
