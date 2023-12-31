package com.ferry.bowall.service.impl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.ferry.bowall.entity.Fans;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.mapper.FansMapper;
import com.ferry.bowall.mapper.FollowersMapper;
import com.ferry.bowall.mapper.UserMapper;
import com.ferry.bowall.service.FansService;
import com.ferry.bowall.service.FollowersService;
import com.ferry.bowall.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.EntityNotFoundException;
import java.util.List;

@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {
    @Autowired
    private UserMapper userMapper;

    @Autowired
    private FansMapper fansMapper;

    @Autowired
    private FollowersMapper followersMapper;

    @Override
    public List<User> getUserList() {
        return userMapper.getUserList();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateUser(User user) {
        userMapper.updateUser(user);
    }

    @Override
    public List<User> friends(String account) {
        return userMapper.friends(account);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void addFanAndFollowUser(String account, String fansAccount) {

        fansMapper.save(account, fansAccount);
        followersMapper.save(fansAccount, account);
    }

    @Override
    public User getUser(String account) {
        User user = userMapper.getUser(account);
        return user;
    }


}
