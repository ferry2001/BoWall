package com.ferry.bowall.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ferry.bowall.common.R;
import com.ferry.bowall.dto.CommentsDto;
import com.ferry.bowall.dto.PostsDto;
import com.ferry.bowall.entity.*;
import com.ferry.bowall.service.*;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

@RequestMapping("/posts")
@RestController
@Slf4j
public class PostsController {

    @Autowired
    private PostsService postsService;

    @Autowired
    private UserService userService;

    @Autowired
    private ImageService imageService;

    @Autowired
    private CommentsService commentsService;

    @Autowired
    private LikeService likeService;

    @GetMapping("getPostsById")
    public R<PostsDto> getPostsById(@RequestParam String postId) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getId, postId);
        Posts post = postsService.getOne(postsLambdaQueryWrapper);

        LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
        List<Image> images = imageService.list(imageLambdaQueryWrapper);

        //select user object in post
        User user = userService.getUser(post.getAccount());

        //select commentsDto object in post
        //1.select comments 2.new arraylist of commentsDto
        //3.for comments which add name of commenter and comment into commentsDto
        LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        commentsLambdaQueryWrapper = commentsLambdaQueryWrapper.eq(Comments::getPostsId, post.getId());
        List<Comments> comments = commentsService.list(commentsLambdaQueryWrapper);
        ArrayList<CommentsDto> commentsDtos = new ArrayList<>();
        for (Comments comment : comments) {
            CommentsDto commentsDto = new CommentsDto();
            commentsDto.setComments(comment);

            String commentUserName = userService.getUserName(comment.getAccount());
            String commentUserAvatar = userService.getUserAvatar(comment.getAccount());
            commentsDto.setName(commentUserName);
            commentsDto.setUserAvatar(commentUserAvatar);
            if (comment.getReplyToAccount() != null && !comment.getReplyToAccount().isBlank()) {
                commentsDto.setReplyToName(userService.getUserName(comment.getReplyToAccount()));
            }

            commentsDtos.add(commentsDto);
        }

        PostsDto postsDto = new PostsDto();
        postsDto.setUser(user);
        postsDto.setAccount(post.getAccount());
        postsDto.setId(post.getId());
        postsDto.setText(post.getText());
        postsDto.setUpdateDate(post.getUpdateDate());
        postsDto.setImages(images);
        postsDto.setComments(commentsDtos);
        LambdaQueryWrapper<Likes> likesCountWrapper = new LambdaQueryWrapper<>();
        likesCountWrapper.eq(Likes::getPostId, post.getId());
        postsDto.setLikeCount(likeService.count(likesCountWrapper));

        return R.success(postsDto);
    }

    @GetMapping("/getAllPosts")
    public R<List<PostsDto>> getAllPosts(@RequestParam int page, @RequestParam int size, @RequestParam String account) {
        List<PostsDto> postsDtos = new ArrayList<>();
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.orderByDesc(Posts::getUpdateDate);
//        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);
        Page<Posts> postsPage = new Page<>(page, size);
        postsPage = postsService.page(postsPage, postsLambdaQueryWrapper);
        List<Posts> posts = postsPage.getRecords();
        for (Posts post : posts) {
            // select images object in post
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            //select user object in post
            User user = userService.getUser(post.getAccount());

            //select commentsDto object in post
            //1.select comments 2.new arraylist of commentsDto
            //3.for comments which add name of commenter and comment into commentsDto
            LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
            commentsLambdaQueryWrapper = commentsLambdaQueryWrapper.eq(Comments::getPostsId, post.getId());
            commentsLambdaQueryWrapper.orderByAsc(Comments::getUpdateDate);
            List<Comments> comments = commentsService.list(commentsLambdaQueryWrapper);
            ArrayList<CommentsDto> commentsDtos = new ArrayList<>();
            for (Comments comment : comments) {
                CommentsDto commentsDto = new CommentsDto();
                commentsDto.setComments(comment);

                String commentUserName = userService.getUserName(comment.getAccount());
                String commentUserAvatar = userService.getUserAvatar(comment.getAccount());
                commentsDto.setName(commentUserName);
                commentsDto.setUserAvatar(commentUserAvatar);
                if (comment.getReplyToAccount() != null && !comment.getReplyToAccount().isBlank()) {
                    commentsDto.setReplyToName(userService.getUserName(comment.getReplyToAccount()));
                }

                commentsDtos.add(commentsDto);
            }

            LambdaQueryWrapper<Likes> likesLambdaQueryWrapper = new LambdaQueryWrapper<Likes>();
            likesLambdaQueryWrapper.eq(Likes::getAccount,account)
                    .eq(Likes::getPostId,post.getId());
            Likes likes = likeService.getOne(likesLambdaQueryWrapper);
            PostsDto postsDto = new PostsDto();
            postsDto.setUser(user);
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);
            postsDto.setComments(commentsDtos);
            if (likes == null) {
                postsDto.setIsLike(0);
            }else {
                postsDto.setIsLike(1);
            }
            LambdaQueryWrapper<Likes> likesCountWrapper = new LambdaQueryWrapper<>();
            likesCountWrapper.eq(Likes::getPostId, post.getId());
            postsDto.setLikeCount(likeService.count(likesCountWrapper));
            postsDtos.add(postsDto);
        }


        return R.success(postsDtos);
    }

    @PostMapping("/post")
    public R<String> post(@RequestBody Map map) {
        Posts posts = new Posts();
        String account = map.get("account").toString();
        String text = map.get("text").toString();
        UUID uuid = UUID.randomUUID();

        posts.setAccount(account);
        posts.setId(uuid.toString());
        posts.setText(text);
        posts.setUpdateDate(LocalDateTime.now());

        postsService.save(posts);
        return R.success(uuid.toString());
    }

    @PostMapping("/forward")
    public R<String> forward(@RequestBody Map map) {
        String account = map.get("account").toString();
        String postId = map.get("postId").toString();
        List list = (List) map.get("images");

        UUID uuid = UUID.randomUUID();
        Posts post = postsService.getById(postId);
        Posts posts = new Posts();
        posts.setAccount(account);
        posts.setId(uuid.toString());
        posts.setText("转发来自用户账号为@"+post.getAccount()+"的动态:"+post.getText());
        posts.setUpdateDate(LocalDateTime.now());
        postsService.save(posts);
        for (Object o : list) {
            Map mapImage = (Map) o;
            System.out.println(mapImage.get("url").toString());
            String url = mapImage.get("url").toString();
            String width = mapImage.get("width").toString();
            String height = mapImage.get("height").toString();

            Image image = new Image();
            image.setAccount(account);
            image.setUrl(url);
            image.setPostsId(uuid.toString());
            image.setWidth(width);
            image.setHeight(height);
            image.setUpdateDate(LocalDateTime.now());
            imageService.save(image);

        }


        return null;
    }

    @GetMapping("/getPosts")
    public R<List<PostsDto>> getPosts(@RequestParam String account) {
        List<PostsDto> postsDtos = new ArrayList<>();
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper = postsLambdaQueryWrapper.in(Posts::getAccount, account);
        List<Posts> posts = postsService.list(postsLambdaQueryWrapper);

        for (Posts post : posts) {
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper = imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            PostsDto postsDto = new PostsDto();
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);
            LambdaQueryWrapper<Likes> likesCountWrapper = new LambdaQueryWrapper<>();
            likesCountWrapper.eq(Likes::getPostId, post.getId());
            postsDto.setLikeCount(likeService.count(likesCountWrapper));

            postsDtos.add(postsDto);
        }

        return R.success(postsDtos);
    }

    /**
     * get pages of posts
     *
     * @param page
     * @param size
     * @param inValue
     * @return
     */
    @GetMapping("/getPostsPages")
    public R<List<PostsDto>> getPostsPages(@RequestParam int page, @RequestParam int size, @RequestParam String inValue) {
        List<PostsDto> postsDtos = new ArrayList<>();

        //get post page object and get post object
        Page<Posts> page1 = new Page<>(page, size);
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.like(Posts::getText, inValue).or().like(Posts::getAccount, inValue);
        Page<Posts> postsPage = postsService.page(page1, postsLambdaQueryWrapper);
        List<Posts> posts = postsPage.getRecords();

        //if inValue is not null then query by criteria
        if (inValue != "") {
            LambdaQueryWrapper<User> userLambdaQueryWrapper = new LambdaQueryWrapper<>();
            userLambdaQueryWrapper.like(User::getName, inValue);
            List<User> users = userService.list(userLambdaQueryWrapper);
            for (User user : users) {
                String account = user.getAccount();
                LambdaQueryWrapper<Posts> postsLambdaQueryWrapper1 = new LambdaQueryWrapper<>();
                postsLambdaQueryWrapper1.like(Posts::getAccount, account);
                posts.addAll(postsService.page(page1, postsLambdaQueryWrapper1).getRecords());
            }
        }

        //去除重复的元素
        posts = posts.stream().distinct().collect(Collectors.toList());

        for (Posts post : posts) {
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper = imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            PostsDto postsDto = new PostsDto();
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);

            postsDtos.add(postsDto);
        }
        return R.success(postsDtos);
    }

    @GetMapping("/count")
    public R<String> count(@RequestParam String account) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.in(Posts::getAccount, account);
        int count = (int) postsService.count(postsLambdaQueryWrapper);
        if (count > 0) {
            return R.success(String.valueOf(count));
        } else {
            return R.success("0");
        }
    }

    @DeleteMapping("/delete/{postId}")
    public R<String> deletePost(@PathVariable String postId, @RequestParam String account) {
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsLambdaQueryWrapper.eq(Posts::getId, postId);

        //检查帖子是否存在
        Posts post = postsService.getOne(postsLambdaQueryWrapper);
        if (post == null) {
            return R.error("帖子不存在或已被删除");
        }
        if (!post.getAccount().equals(account)) {
            return R.error("无权删除其他用户的动态");
        }

        // 删除帖子
        boolean remove = postsService.remove(postsLambdaQueryWrapper);
        if (remove) {
            // 还需要删除关联的评论、图片等内容
            LambdaQueryWrapper<Comments> commentsLambdaQueryWrapper = new LambdaQueryWrapper<>();
            commentsLambdaQueryWrapper.eq(Comments::getPostsId, postId);
            commentsService.remove(commentsLambdaQueryWrapper);

            LambdaQueryWrapper<Likes> likesLambdaQueryWrapper = new LambdaQueryWrapper<>();
            likesLambdaQueryWrapper.eq(Likes::getPostId, postId);
            likeService.remove(likesLambdaQueryWrapper);

            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper.eq(Image::getPostsId,postId);
            imageService.remove(imageLambdaQueryWrapper);
            return R.success("帖子删除成功");
        } else {
            return R.error("帖子删除失败");
        }
    }

}
