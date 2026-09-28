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
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

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

    @Autowired
    private FollowersService followersService;

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

    /**
     * 首页推荐：优先推荐关注过、点赞过或评论过的作者发布的新动态。
     * 没有足够互动记录时，排序自然退化为按发布时间倒序的公共动态流。
     */
    @GetMapping("/recommendations")
    public R<List<PostsDto>> recommendations(
            @RequestParam String account,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 50);
        Map<String, Integer> authorAffinity = new java.util.HashMap<>();

        LambdaQueryWrapper<Followers> followingQuery = new LambdaQueryWrapper<>();
        followingQuery.eq(Followers::getAccount, account);
        for (Followers following : followersService.list(followingQuery)) {
            authorAffinity.merge(following.getFollowersAccount(), 6, Integer::sum);
        }

        List<String> interactedPostIds = new ArrayList<>();
        LambdaQueryWrapper<Likes> likesQuery = new LambdaQueryWrapper<>();
        likesQuery.eq(Likes::getAccount, account);
        interactedPostIds.addAll(likeService.list(likesQuery).stream()
                .map(Likes::getPostId)
                .toList());

        LambdaQueryWrapper<Comments> commentsQuery = new LambdaQueryWrapper<>();
        commentsQuery.eq(Comments::getAccount, account);
        interactedPostIds.addAll(commentsService.list(commentsQuery).stream()
                .map(Comments::getPostsId)
                .toList());

        if (!interactedPostIds.isEmpty()) {
            LambdaQueryWrapper<Posts> interactedPostsQuery = new LambdaQueryWrapper<>();
            interactedPostsQuery.in(Posts::getId, new LinkedHashSet<>(interactedPostIds));
            for (Posts interactedPost : postsService.list(interactedPostsQuery)) {
                if (!account.equals(interactedPost.getAccount())) {
                    authorAffinity.merge(interactedPost.getAccount(), 3, Integer::sum);
                }
            }
        }

        // 多取一些候选后在内存中按亲和度排序，可避免推荐结果被单一作者占满。
        LambdaQueryWrapper<Posts> candidateQuery = new LambdaQueryWrapper<>();
        candidateQuery.ne(Posts::getAccount, account)
                .orderByDesc(Posts::getUpdateDate);
        List<Posts> candidates = postsService.page(new Page<>(1, 200), candidateQuery).getRecords();
        candidates.sort((left, right) -> {
            int affinityCompare = Integer.compare(
                    authorAffinity.getOrDefault(right.getAccount(), 0),
                    authorAffinity.getOrDefault(left.getAccount(), 0));
            if (affinityCompare != 0) {
                return affinityCompare;
            }
            return right.getUpdateDate().compareTo(left.getUpdateDate());
        });

        int start = (safePage - 1) * safeSize;
        List<PostsDto> recommendations = new ArrayList<>();
        for (Posts post : candidates.stream().skip(start).limit(safeSize).toList()) {
            LambdaQueryWrapper<Image> imageQuery = new LambdaQueryWrapper<>();
            imageQuery.eq(Image::getPostsId, post.getId());

            PostsDto dto = new PostsDto();
            dto.setUser(userService.getUser(post.getAccount()));
            dto.setAccount(post.getAccount());
            dto.setId(post.getId());
            dto.setText(post.getText());
            dto.setUpdateDate(post.getUpdateDate());
            dto.setImages(imageService.list(imageQuery));

            // 首页推荐与普通动态流使用同一套评论数据，避免推荐卡片只显示点赞而漏掉讨论内容。
            LambdaQueryWrapper<Comments> commentQuery = new LambdaQueryWrapper<>();
            commentQuery.eq(Comments::getPostsId, post.getId())
                    .orderByAsc(Comments::getUpdateDate);
            ArrayList<CommentsDto> commentDtos = new ArrayList<>();
            for (Comments comment : commentsService.list(commentQuery)) {
                CommentsDto commentDto = new CommentsDto();
                commentDto.setComments(comment);
                commentDto.setName(userService.getUserName(comment.getAccount()));
                commentDto.setUserAvatar(userService.getUserAvatar(comment.getAccount()));
                if (comment.getReplyToAccount() != null && !comment.getReplyToAccount().isBlank()) {
                    commentDto.setReplyToName(userService.getUserName(comment.getReplyToAccount()));
                }
                commentDtos.add(commentDto);
            }
            dto.setComments(commentDtos);

            LambdaQueryWrapper<Likes> currentLikeQuery = new LambdaQueryWrapper<>();
            currentLikeQuery.eq(Likes::getAccount, account)
                    .eq(Likes::getPostId, post.getId());
            dto.setIsLike(likeService.getOne(currentLikeQuery) == null ? 0 : 1);

            LambdaQueryWrapper<Likes> likeCountQuery = new LambdaQueryWrapper<>();
            likeCountQuery.eq(Likes::getPostId, post.getId());
            dto.setLikeCount(likeService.count(likeCountQuery));
            recommendations.add(dto);
        }
        return R.success(recommendations);
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
    public R<List<PostsDto>> getPostsPages(
            @RequestParam int page,
            @RequestParam int size,
            @RequestParam String inValue,
            @RequestParam(required = false) String account) {
        String keyword = inValue == null ? "" : inValue.trim();
        if (keyword.isEmpty()) {
            return R.success(new ArrayList<>());
        }

        // 昵称命中的用户，其全部动态也应当出现在搜索结果中；账号与正文则直接模糊匹配。
        LambdaQueryWrapper<User> userQuery = new LambdaQueryWrapper<>();
        userQuery.like(User::getAccount, keyword)
                .or()
                .like(User::getName, keyword);
        LinkedHashSet<String> matchedAccounts = userService.list(userQuery).stream()
                .map(User::getAccount)
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));

        LambdaQueryWrapper<Posts> postQuery = new LambdaQueryWrapper<>();
        postQuery.nested(query -> query.like(Posts::getText, keyword)
                .or()
                .like(Posts::getAccount, keyword));
        if (!matchedAccounts.isEmpty()) {
            postQuery.or(query -> query.in(Posts::getAccount, matchedAccounts));
        }
        postQuery.orderByDesc(Posts::getUpdateDate);

        int safePage = Math.max(page, 1);
        int safeSize = Math.min(Math.max(size, 1), 50);
        List<Posts> posts = postsService.page(new Page<>(safePage, safeSize), postQuery).getRecords();
        List<PostsDto> postsDtos = new ArrayList<>();
        for (Posts post : posts) {
            LambdaQueryWrapper<Image> imageLambdaQueryWrapper = new LambdaQueryWrapper<>();
            imageLambdaQueryWrapper = imageLambdaQueryWrapper.eq(Image::getPostsId, post.getId());
            List<Image> images = imageService.list(imageLambdaQueryWrapper);

            PostsDto postsDto = new PostsDto();
            postsDto.setUser(userService.getUser(post.getAccount()));
            postsDto.setAccount(post.getAccount());
            postsDto.setId(post.getId());
            postsDto.setText(post.getText());
            postsDto.setUpdateDate(post.getUpdateDate());
            postsDto.setImages(images);
            if (account != null && !account.isBlank()) {
                LambdaQueryWrapper<Likes> likeQuery = new LambdaQueryWrapper<>();
                likeQuery.eq(Likes::getPostId, post.getId())
                        .eq(Likes::getAccount, account);
                postsDto.setIsLike(likeService.getOne(likeQuery) == null ? 0 : 1);
            } else {
                postsDto.setIsLike(0);
            }
            LambdaQueryWrapper<Likes> likeCountQuery = new LambdaQueryWrapper<>();
            likeCountQuery.eq(Likes::getPostId, post.getId());
            postsDto.setLikeCount(likeService.count(likeCountQuery));

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
