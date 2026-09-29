package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.dto.LikeDto;
import com.ferry.bowall.entity.Image;
import com.ferry.bowall.entity.Likes;
import com.ferry.bowall.entity.Posts;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.enums.Image.ImageIsCover;
import com.ferry.bowall.filter.JwtAuthInterceptor;
import com.ferry.bowall.service.ImageService;
import com.ferry.bowall.service.LikeService;
import com.ferry.bowall.service.PostsService;
import com.ferry.bowall.service.UserService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import jakarta.servlet.http.HttpServletRequest;

import java.time.LocalDateTime;
import java.util.*;
import java.util.UUID;

@RequestMapping("/like")
@RestController
@Slf4j
public class LikeController {
    @Autowired
    private LikeService likeService;

    @Autowired
    private PostsService postsService;

    @Autowired
    private UserService userService;

    @Autowired
    private ImageService imageService;

    @PostMapping
    @Transactional(rollbackFor = Exception.class)
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
            like01.setIsRead("no");
            like01.setUpdateDate(LocalDateTime.now());
            if (!likeService.save(like01)) return R.error("点赞失败");
            postsService.update(new LambdaUpdateWrapper<Posts>()
                    .eq(Posts::getId, postId)
                    .setSql("like_count = COALESCE(like_count, 0) + 1"));
            return R.success("点赞成功");
        }else {
            if (!likeService.remove(likesLambdaQueryWrapper)) return R.error("取消点赞失败");
            postsService.update(new LambdaUpdateWrapper<Posts>()
                    .eq(Posts::getId, postId)
                    .setSql("like_count = GREATEST(0, COALESCE(like_count, 0) - 1)"));
            return R.success("取消点赞");
        }
    }

    /** 返回当前用户收到的点赞互动，不包含给自己动态点的赞。 */
    @GetMapping("/notification")
    public R<List<LikeDto>> notification(@RequestParam String account) {
        List<Posts> posts = postsService.list(new LambdaQueryWrapper<Posts>().eq(Posts::getAccount, account));
        if (posts.isEmpty()) return R.success(new ArrayList<>());

        Set<String> postIds = new HashSet<>();
        Map<String, Posts> postById = new HashMap<>();
        for (Posts post : posts) {
            postIds.add(post.getId());
            postById.put(post.getId(), post);
        }
        List<Likes> likes = likeService.list(new LambdaQueryWrapper<Likes>()
                .in(Likes::getPostId, postIds)
                .ne(Likes::getAccount, account)
                .orderByDesc(Likes::getUpdateDate));

        Map<String, String> coverByPostId = new HashMap<>();
        for (Image image : imageService.list(new LambdaQueryWrapper<Image>()
                .in(Image::getPostsId, postIds)
                .eq(Image::getIsCover, ImageIsCover.yes))) {
            coverByPostId.putIfAbsent(image.getPostsId(), image.getUrl());
        }

        List<LikeDto> result = new ArrayList<>();
        for (Likes like : likes) {
            User user = userService.getUser(like.getAccount());
            if (user == null || !postById.containsKey(like.getPostId())) continue;
            LikeDto dto = new LikeDto();
            dto.setLike(like);
            dto.setAccount(like.getAccount());
            dto.setName(user.getName());
            dto.setUserAvatar(user.getAvatar());
            dto.setPostId(like.getPostId());
            dto.setPostsImage(coverByPostId.get(like.getPostId()));
            result.add(dto);
        }
        return R.success(result);
    }

    @PutMapping("/{likeId}/read")
    public R<String> markRead(HttpServletRequest request, @PathVariable String likeId) {
        String currentAccount = (String) request.getAttribute(JwtAuthInterceptor.CURRENT_ACCOUNT);
        Likes like = likeService.getById(likeId);
        Posts post = like == null ? null : postsService.getById(like.getPostId());
        if (post == null || !currentAccount.equals(post.getAccount())) return R.error("无权操作这条互动消息");
        like.setIsRead("yes");
        likeService.updateById(like);
        return R.success("已读");
    }
}
