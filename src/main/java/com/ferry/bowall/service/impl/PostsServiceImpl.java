package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Posts;
import com.ferry.bowall.mapper.PostsMapper;
import com.ferry.bowall.service.PostsService;
import org.springframework.stereotype.Service;

@Service
public class PostsServiceImpl extends ServiceImpl<PostsMapper, Posts> implements PostsService {

    @Override
    public Page<Posts> getPostsPages(int page, int size, LambdaQueryWrapper<Posts> postsLambdaQueryWrapper) {
        Page<Posts> postsPage = new Page<>();
        postsPage = this.baseMapper.selectPage(postsPage, postsLambdaQueryWrapper);

        return postsPage;
    }
}
