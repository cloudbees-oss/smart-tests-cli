package com.cloudbees.smarttests.example;

public final class Calculator {
    private Calculator() {
    }

    public static int add(int left, int right) {
        return left + right;
    }

    public static int multiply(int left, int right) {
        return left * right;
    }
}
