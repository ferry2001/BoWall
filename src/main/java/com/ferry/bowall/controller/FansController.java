package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.entity.Fans;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.service.FansService;
import com.ferry.bowall.service.UserService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.ArrayList;

@RestController
@RequestMapping("/fans")
@Slf4j
public class FansController {
    @Autowired
    private FansService fansService;

    @Autowired
    private UserService userService;

    @GetMapping("/getFans")
    public R<List<User>> getFans(@RequestParam String account) {
        LambdaQueryWrapper<Fans> fansQuery = new LambdaQueryWrapper<>();
        fansQuery.eq(Fans::getAccount, account);
        List<Fans> fans = fansService.list(fansQuery);
        List<User> users = new ArrayList<>();
        for (Fans fan : fans) {
            User user = userService.getUser(fan.getFansAccount());
            if (user != null) {
                users.add(user);
            }
        }
        return R.success(users);
    }

    @GetMapping("/count")
    public R<String> count(@RequestParam String account) {
        LambdaQueryWrapper<Fans> fansLambdaQueryWrapper = new LambdaQueryWrapper<Fans>();
        fansLambdaQueryWrapper.in(Fans::getAccount, account);
        int count = (int)fansService.count(fansLambdaQueryWrapper);
        if (count > 0) {
            return R.success(String.valueOf(count));
        }else {
            return R.success("0");
        }
    }

    @GetMapping("/isfan")
    public R<Fans> isfan(String account, String fansAccount) {
        Fans fans = fansService.isfan(account, fansAccount);
        return R.success(fans);
    }


}
