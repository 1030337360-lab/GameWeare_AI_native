package com.gameweare.api.voucher;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/vouchers")
public class VoucherController {
    private final GenerationVoucherService vouchers;
    public VoucherController(GenerationVoucherService vouchers) { this.vouchers = vouchers; }

    @GetMapping("/me")
    public List<Map<String, Object>> mine(@RequestAttribute("userId") String userId) {
        return vouchers.mine(userId);
    }
}
