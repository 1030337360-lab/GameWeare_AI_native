if redis.call('HGET', KEYS[2], ARGV[1]) ~= ARGV[2] then return 0 end
local status = redis.call('GET', KEYS[3])
if not status or string.sub(status, 1, 7) ~= 'pending' then return 0 end
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('INCR', KEYS[1])
redis.call('SET', KEYS[3], 'failed', 'EX', 3888000)
return 1
