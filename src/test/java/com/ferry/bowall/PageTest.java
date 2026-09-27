package com.ferry.bowall;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ferry.bowall.entity.Posts;
import com.ferry.bowall.service.PostsService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.List;

@SpringBootTest
public class PageTest {
    @Autowired
    private PostsService postsService;

    @Test
    public void page() {
        int page = 1;
        int size = 5;
        Page<Posts> postsPage = new Page<>(page, size);
        LambdaQueryWrapper<Posts> postsLambdaQueryWrapper = new LambdaQueryWrapper<>();
        postsPage = postsService.page(postsPage, postsLambdaQueryWrapper);
        List<Posts> records = postsPage.getRecords();
        for (Posts record : records) {
            System.out.println(record);
        }
    }

}
