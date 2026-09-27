package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.entity.Comments;
import com.ferry.bowall.entity.Message;
import com.ferry.bowall.entity.Notification;
import com.ferry.bowall.entity.Posts;
import com.ferry.bowall.enums.Message.MessageIsRead;
import com.ferry.bowall.enums.Notification.NotificationStatus;
import com.ferry.bowall.service.CommentsService;
import com.ferry.bowall.service.MessageService;
import com.ferry.bowall.service.NotificationService;
import com.ferry.bowall.service.PostsService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;

@RequestMapping(("/notification"))
@RestController
@Slf4j
public class NotificationController {
    @Autowired
    private NotificationService notificationService;

    @Autowired
    private MessageService messageService;

    @Autowired
    private CommentsService commentsService;

    @Autowired
    private PostsService postsService;

    @GetMapping("/count")
    public R<Long> count(@RequestParam String account) {
        LambdaQueryWrapper<Message> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getAccount, account);
        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);
        ArrayList<String> postIds = new ArrayList<>();
        for (Posts post : posts) {
            postIds.add(post.getId());
        }

        messageLambdaQueryWrapper.eq(Message::getRecipientAccount,account)
                .eq(Message::getIsRead, MessageIsRead.no);
        commentsLambdaQueryWrapper.in(Comments::getPostsId, postIds)
                .eq(Comments::getIsRead, MessageIsRead.no);

        Long messageCount = messageService.count(messageLambdaQueryWrapper);
        Long commentsCount = commentsService.count(commentsLambdaQueryWrapper);
        Long total = messageCount + commentsCount;
        return R.success(total);
    }
}
