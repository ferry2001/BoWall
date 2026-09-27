package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.entity.Followers;
import com.ferry.bowall.entity.Posts;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.service.FollowersService;
import com.ferry.bowall.service.UserService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;

@RestController
@RequestMapping("/followers")
@Slf4j
public class FollowersController {
    @Autowired
    private FollowersService followersService;

    @Autowired
    private UserService userService;

    @GetMapping("/getFollowers")
    public R<List<User>> getFollowers(@RequestParam String account) {
        LambdaQueryWrapper<Followers> followersLambdaQueryWrapper = new LambdaQueryWrapper<>();
        followersLambdaQueryWrapper = followersLambdaQueryWrapper.eq(Followers::getAccount, account);
        List<Followers> followers = followersService.list(followersLambdaQueryWrapper);

        ArrayList<User> users = new ArrayList<>();
        for (Followers follower : followers) {
            User user = userService.getUser(follower.getFollowersAccount());
            users.add(user);
        }
        return R.success(users);
    }

    @GetMapping("/count")
    public R<String> count(@RequestParam String account) {
        LambdaQueryWrapper<Followers> followersLambdaQueryWrapper = new LambdaQueryWrapper<>();
        followersLambdaQueryWrapper.in(Followers::getAccount, account);
        int count = (int)followersService.count(followersLambdaQueryWrapper);
        if (count > 0) {
            return R.success(String.valueOf(count));
        }else {
            return R.success("0");
        }
    }
}
