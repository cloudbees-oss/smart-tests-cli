package com.cloudbees.smarttests.example;

import org.testng.Assert;
import org.testng.annotations.Test;

public class MultiplicationTest {
    @Test
    public void multipliesTwoNumbers() {
        Assert.assertEquals(Calculator.multiply(6, 7), 42);
    }
}
