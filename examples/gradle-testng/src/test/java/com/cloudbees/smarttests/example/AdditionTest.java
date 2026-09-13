package com.cloudbees.smarttests.example;

import org.testng.Assert;
import org.testng.annotations.Test;

public class AdditionTest {
    @Test
    public void addsTwoNumbers() {
        Assert.assertEquals(Calculator.add(19, 23), 42);
    }
}
