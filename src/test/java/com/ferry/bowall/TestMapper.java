package com.ferry.bowall;


import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ferry.bowall.entity.*;
import com.ferry.bowall.enums.Comments.CommentsIsDel;
import com.ferry.bowall.enums.Comments.CommentsIsRead;
import com.ferry.bowall.enums.Image.ImageIsCover;
import com.ferry.bowall.enums.Message.MessageIsDel;
import com.ferry.bowall.enums.Message.MessageIsRead;
import com.ferry.bowall.enums.Notification.NotificationStatus;
import com.ferry.bowall.mapper.CommentsMapper;
import com.ferry.bowall.mapper.FansMapper;
import com.ferry.bowall.mapper.ImageMapper;
import com.ferry.bowall.mapper.MessageMapper;
import com.ferry.bowall.service.MessageService;
import com.ferry.bowall.service.NotificationService;
import com.ferry.bowall.service.UserService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

@SpringBootTest
public class TestMapper {

    @Autowired
    private MessageMapper messageMapper;

    @Autowired
    private FansMapper fansMapper;

    @Autowired
    private CommentsMapper commentsMapper;

    @Autowired
    private ImageMapper imageMapper;

    @Test
    public void userTest() {
        System.out.println("test");
        User user = new User();
        user.setAccount("fefylosfahor");
        user.setPhone("13646777818");
//        userService.updateUser(user);
    }

    @Test
    public void deleteFanAndFollowUser() {
        String account = "1"; String fansAccount = "fefylosfahor";
        LambdaQueryWrapper<Fans> fansLambdaQueryWrapper = new LambdaQueryWrapper<>();
        fansLambdaQueryWrapper.eq(Fans::getAccount, account);
        fansLambdaQueryWrapper.eq(Fans::getFansAccount, fansAccount);
        LambdaQueryWrapper<Followers> followersLambdaQueryWrapper = new LambdaQueryWrapper<>();
        followersLambdaQueryWrapper.eq(Followers::getAccount, fansAccount);
        followersLambdaQueryWrapper.eq(Followers::getFollowersAccount, account);
        System.out.println(fansMapper.exists(fansLambdaQueryWrapper));
    }



    @Test
    public void isRead() {
        LambdaQueryWrapper<Message> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        Message message = new Message();
        message.setIsRead(MessageIsRead.no);
        messageMapper.update(message, messageLambdaQueryWrapper);
    }

    @Test
    public void isDel() {
        LambdaQueryWrapper<Message> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        Message message = new Message();
        message.setIsDel(MessageIsDel.no);
        messageMapper.update(message, messageLambdaQueryWrapper);
    }

    @Test
    public void commentsIsRead() {
        LambdaQueryWrapper<Comments> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        Comments comments = new Comments();
        comments.setIsRead(CommentsIsRead.no);
        commentsMapper.update(comments, messageLambdaQueryWrapper);
    }

    @Test
    public void commentsIsDel() {
        LambdaQueryWrapper<Comments> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        Comments comments = new Comments();
        comments.setIsDel(CommentsIsDel.no);
        commentsMapper.update(comments, messageLambdaQueryWrapper);
    }

    @Test
    public void imageIsCover() {
        LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        Image image = new Image();
        image.setIsCover(ImageIsCover.no);
        imageMapper.update(image, imageLambdaQueryWrapper);
    }
}
