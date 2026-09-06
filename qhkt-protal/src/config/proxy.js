export default {
  development: {
    // 开发环境接口请求
    // Vite dev server proxies API paths to avoid cross-origin requests.
    // Production builds keep the public gateway host below.
    host: import.meta.env.DEV ? '' : 'http://api.qhkt.com',
    // 开发环境 cdn 路径
    cdn: '',
  },
  test: {
    // 测试环境接口地址
    host: 'https://qhkt-user-t.itheima.net/api',
    // 测试环境 cdn 路径
    cdn: '',
  },
  product: {
    // 正式环境接口地址
    host: 'https://qhkt-user-t.itheima.net/api',
    // 正式环境 cdn 路径
    cdn: '',
  },
};
