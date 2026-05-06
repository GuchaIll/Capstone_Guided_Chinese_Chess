// Vitest jsdom shims.
//
// 1. jsdom (≤ 26 at the time of writing) doesn't implement
//    HTMLImageElement.prototype.decode(), which several React components
//    await for image preloading. Without a polyfill the rendered
//    component throws `TypeError: img.decode is not a function`. Stub
//    with a resolved Promise — same observable behaviour as a
//    successful decode in real browsers.
//
// 2. next/navigation hooks (useRouter / usePathname / useSearchParams)
//    require the App Router context that's only present at runtime in
//    Next.js. In unit tests the components are mounted in bare jsdom,
//    so we stub the module with no-op routers. Components that *only*
//    call router.push() in response to user actions will work
//    correctly; tests that need to assert navigation should override
//    this mock per-test with `vi.mocked(useRouter).mockReturnValue(...)`.

import { vi } from 'vitest';

if (
  typeof HTMLImageElement !== 'undefined' &&
  typeof HTMLImageElement.prototype.decode !== 'function'
) {
  HTMLImageElement.prototype.decode = function decode(): Promise<void> {
    return Promise.resolve();
  };
}

vi.mock('next/navigation', () => {
  const noopRouter = {
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  };
  return {
    useRouter: () => noopRouter,
    usePathname: () => '/',
    useSearchParams: () => new URLSearchParams(),
    redirect: vi.fn(),
    notFound: vi.fn(),
  };
});
