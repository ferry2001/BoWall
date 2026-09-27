package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.dto.CommentsDto;
import com.ferry.bowall.entity.*;
import com.ferry.bowall.enums.Comments.CommentsIsDel;
import com.ferry.bowall.enums.Comments.CommentsIsRead;
import com.ferry.bowall.enums.Image.ImageIsCover;
import com.ferry.bowall.service.CommentsService;
import com.ferry.bowall.service.ImageService;
import com.ferry.bowall.service.PostsService;
import com.ferry.bowall.service.UserService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/comments")
@Slf4j
public class CommentsController {
    @Autowired
    private CommentsService commentsService;

    @Autowired
    private PostsService postsService;

    @Autowired
    private UserService userService;

    @Autowired
    private ImageService imageService;


    @PostMapping("/post")
    public R<String> post(@RequestBody Map map) {
        System.out.println(map);
        UUID uuid = UUID.randomUUID();
        String postsId = map.get("postsId").toString();
        String account = map.get("account").toString();
        String text = map.get("comments").toString();

        Comments comments = new Comments();
        comments.setId(uuid.toString());
        comments.setPostsId(postsId);
        comments.setAccount(account);
        comments.setText(text);
        comments.setUpdateDate(LocalDateTime.now());

        commentsService.save(comments);

        return R.success("发送成功");
    }

    @GetMapping("/notification")
    public R<ArrayList<CommentsDto>> comments(@RequestParam String account) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getAccount,account);
        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);

        ArrayList<String> postIds = new ArrayList<>();
        HashMap<String, Posts> accountPostsHashMap = new HashMap<>();
        for (Posts post : posts) {
            String postId = post.getId();
            postIds.add(postId);
            accountPostsHashMap.put(postId, post);
        }

        LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        imageLambdaQueryWrapper.in(Image::getPostsId, postIds)
                .eq(Image::getIsCover, ImageIsCover.yes);

        Map<String, Image> images = imageService.list(imageLambdaQueryWrapper)
                .stream()
                .collect(Collectors.toMap(Image::getPostsId, Image -> Image));

        LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        commentsLambdaQueryWrapper.in(Comments::getPostsId, postIds)
                                   .eq(Comments::getIsDel, CommentsIsDel.no)
                                   .orderByDesc(Comments::getUpdateDate);

        List<Comments> comments = commentsService.list(commentsLambdaQueryWrapper);

        //Assembly commentsDto
        //get user list of message notification
        ArrayList<String> accounts = new ArrayList<>();
        HashMap<String, User> accountUserHashMap = new HashMap<>();

        for (Comments comment : comments) {
            accounts.add(comment.getAccount());
        }


        LambdaQueryWrapper<User> userLambdaQueryWrapper = new LambdaQueryWrapper<>();
        userLambdaQueryWrapper.in(User::getAccount,accounts);
        List<User> users = userService.list(userLambdaQueryWrapper);
        for (User user : users) {
            accountUserHashMap.put(user.getAccount(),user);
        }


        ArrayList<CommentsDto> commentsDtos = new ArrayList<>();
        for (Comments comment : comments) {
            String acc = comment.getAccount();
            String postId = comment.getPostsId();
            User user = accountUserHashMap.get(acc);
            String imageUrl = images.containsKey(postId) ? images.get(postId).getUrl() : null;

            CommentsDto commentsDto = new CommentsDto();

            commentsDto.setComments(comment);
            commentsDto.setName(user.getName());
            commentsDto.setUserAvatar(user.getAvatar());
            commentsDto.setPostsImage(imageUrl);
            commentsDto.setAccount(acc);
            commentsDto.setPostId(postId);

            commentsDtos.add(commentsDto);
        }
        return R.success(commentsDtos);
    }
    
    @GetMapping("/updateIsRead")
    public R<String> updateIsRead(@RequestParam String account) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getAccount, account);
        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);
        ArrayList<String> postIds = new ArrayList<>();
        for (Posts post : posts) {
            postIds.add(post.getId());
        }

        LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        commentsLambdaQueryWrapper.in(Comments::getPostsId, postIds)
                .eq(Comments::getIsRead, CommentsIsRead.no);
        Comments comments = new Comments();
        comments.setIsRead(CommentsIsRead.yes);
        commentsService.update(comments ,commentsLambdaQueryWrapper);
        return R.success("comments is read");
    }

}
