package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.spring.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Followers;
import com.ferry.bowall.mapper.FollowersMapper;
import com.ferry.bowall.service.FollowersService;
import org.springframework.stereotype.Service;

@Service
public class FollowersServiceImpl extends ServiceImpl<FollowersMapper, Followers> implements FollowersService {
}
