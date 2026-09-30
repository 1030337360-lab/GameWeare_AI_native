local current = redis.call('TIME')
local now = tonumber(current[1]) * 1000 + math.floor(tonumber(current[2]) / 1000)
if now < tonumber(ARGV[4]) then return 'NOT_STARTED' end
if now >= tonumber(ARGV[5]) then return 'ENDED' end
local previous = redis.call('HGET', KEYS[2], ARGV[2])
if previous then return 'DUP:' .. previous end
local stock = tonumber(redis.call('GET', KEYS[1]))
if not stock then return 'UNAVAILABLE' end
if stock <= 0 then return 'SOLD_OUT' end
local remaining = redis.call('DECR', KEYS[1])
redis.call('HSET', KEYS[2], ARGV[2], ARGV[3])
redis.call('SET', KEYS[3], 'pending:' .. now, 'EX', 3888000)
redis.call('SET', KEYS[5], ARGV[1] .. '|' .. ARGV[2], 'EX', 3888000)
redis.call('XADD', KEYS[4], '*', 'id', ARGV[3], 'campaign', ARGV[1], 'user', ARGV[2], 'remaining', remaining, 'created', now)
return 'OK:' .. remaining
