package com.ferry.bowall.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.spring.service.IService;
import com.ferry.bowall.entity.Posts;

public interface PostsService extends IService<Posts> {
    public Page<Posts> getPostsPages(int page, int size, LambdaQueryWrapper<Posts> postsLambdaQueryWrapper);
}
