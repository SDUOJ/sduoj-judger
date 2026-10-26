"""Atomic per-user limits shared by every HTTP worker and browser session."""

# Redis TIME avoids clock skew between replicas. Rejected attempts also count
# toward both fixed windows, but only admitted requests advance the gap timer.
_SCRIPT = r'''
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local prefix = KEYS[1]
local second = prefix .. ':s:' .. math.floor(now / 1000)
local minute = prefix .. ':m:' .. math.floor(now / 60000)
local s = redis.call('INCR', second)
if s == 1 then redis.call('PEXPIRE', second, 2000) end
local m = redis.call('INCR', minute)
if m == 1 then redis.call('PEXPIRE', minute, 120000) end
local last = tonumber(redis.call('GET', prefix .. ':last') or '0')
if now - last < 100 or s > 5 or m > 100 then return 0 end
redis.call('SET', prefix .. ':last', now, 'PX', 100)
return 1
'''


async def admit(store, owner_id):
    client = await store.redis()
    return bool(await client.eval(_SCRIPT, 1, f'autolab:ide:rate:{{{owner_id}}}'))
