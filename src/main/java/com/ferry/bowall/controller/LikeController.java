package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.entity.Likes;
import com.ferry.bowall.service.LikeService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

@RequestMapping("/like")
@RestController
@Slf4j
public class LikeController {
    @Autowired
    private LikeService likeService;

    @PostMapping
    public R<String> like(@RequestBody Map map) {
        String account = map.get("account").toString();
        String postId = map.get("postId").toString();
        LambdaQueryWrapper<Likes> likesLambdaQueryWrapper = new LambdaQueryWrapper<>();
        likesLambdaQueryWrapper.eq(Likes::getPostId,postId)
                .eq(Likes::getAccount, account);
        Likes likes = likeService.getOne(likesLambdaQueryWrapper);
        if (likes == null) {
            Likes like01 = new Likes();
            like01.setAccount(account);
            like01.setPostId(postId);
            like01.setId(UUID.randomUUID().toString());
            like01.setUpdateDate(LocalDateTime.now());
            likeService.save(like01);
            return R.success("点赞成功");
        }else {
            likeService.remove(likesLambdaQueryWrapper);
            return R.success("取消点赞");
        }
    }
}
