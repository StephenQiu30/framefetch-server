// @ts-ignore
/* eslint-disable */
import { request, type RequestOptions } from "@/lib/request";

/** 使用邮箱登录 POST /api/auth/login */
export async function loginUser(
  body: API.EmailPasswordRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseUserResponse_>("/api/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** 退出登录 POST /api/auth/logout */
export async function logoutUser(options?: RequestOptions) {
  return request<any>("/api/auth/logout", {
    method: "POST",
    ...(options || {}),
  });
}

/** 查询当前用户 GET /api/auth/me */
export async function getCurrentUser(options?: RequestOptions) {
  return request<API.ApiResponseUserResponse_>("/api/auth/me", {
    method: "GET",
    ...(options || {}),
  });
}

/** 使用邮箱注册 POST /api/auth/register */
export async function registerUser(
  body: API.RegisterRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseUserResponse_>("/api/auth/register", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    data: body,
    ...(options || {}),
  });
}

/** 发送注册邮箱验证码 POST /api/auth/registration-code */
export async function sendRegistrationCode(
  body: API.RegistrationCodeRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseRegistrationCodeResponse_>(
    "/api/auth/registration-code",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      data: body,
      ...(options || {}),
    }
  );
}

/** 验证注册邮箱验证码 POST /api/auth/registration-code/verify */
export async function verifyRegistrationCode(
  body: API.RegistrationCodeVerificationRequest,
  options?: RequestOptions
) {
  return request<API.ApiResponseRegistrationCodeVerificationResponse_>(
    "/api/auth/registration-code/verify",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      data: body,
      ...(options || {}),
    }
  );
}
